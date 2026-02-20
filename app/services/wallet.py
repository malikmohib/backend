from __future__ import annotations

from datetime import datetime
from typing import Iterable
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.models.user import User
from app.models.wallet import WalletAccount, WalletLedger


USD = "USD"


class WalletError(Exception):
    pass


class InsufficientBalance(WalletError):
    pass


class ForbiddenTransfer(WalletError):
    pass


def _now_utc() -> datetime:
    return datetime.utcnow()


async def _ensure_wallet_account(db: AsyncSession, user_id: int) -> None:
    # make sure user exists first (prevents FK crash)
    res_u = await db.execute(select(User.id).where(User.id == user_id))
    if res_u.scalar_one_or_none() is None:
        raise WalletError(f"User {user_id} not found.")

    res = await db.execute(select(WalletAccount.user_id).where(WalletAccount.user_id == user_id))
    exists = res.scalar_one_or_none()
    if exists is not None:
        return

    try:
        db.add(WalletAccount(user_id=user_id, balance_cents=0, currency=USD))
        await db.flush()
    except IntegrityError:
        # safety net
        raise WalletError(f"User {user_id} not found.")


async def _lock_accounts(db: AsyncSession, user_ids: Iterable[int]) -> dict[int, WalletAccount]:
    """
    Lock wallet_accounts rows FOR UPDATE, creating missing accounts first.
    Returns dict user_id -> WalletAccount (locked).
    """
    ids = sorted({int(x) for x in user_ids})

    # Ensure accounts exist first
    for uid in ids:
        await _ensure_wallet_account(db, uid)

    # Lock and fetch
    res = await db.execute(
        select(WalletAccount)
        .where(WalletAccount.user_id.in_(ids))
        .with_for_update()
    )
    rows = res.scalars().all()
    found = {wa.user_id: wa for wa in rows}

    # Safety: ensure we got all of them
    missing = [uid for uid in ids if uid not in found]
    if missing:
        raise WalletError(f"Wallet accounts not found for user_ids={missing}.")

    return found


async def get_balance(db: AsyncSession, user_id: int) -> WalletAccount:
    await _ensure_wallet_account(db, user_id)
    res = await db.execute(select(WalletAccount).where(WalletAccount.user_id == user_id))
    wa = res.scalar_one()
    return wa


async def admin_topup(
    db: AsyncSession,
    admin_user: User,
    target_user_id: int,
    amount_cents: int,
    note: str | None,
) -> WalletLedger:
    """
    Admin increases a user's balance.
    Atomic: balance update + ledger insert.
    """
    if admin_user.role != "admin":
        raise WalletError("Only admin can topup.")

    try:
        accounts = await _lock_accounts(db, [target_user_id])
        target = accounts[target_user_id]

        new_balance = target.balance_cents + amount_cents

        await db.execute(
            update(WalletAccount)
            .where(WalletAccount.user_id == target_user_id)
            .values(balance_cents=new_balance, updated_at=_now_utc())
        )

        entry = WalletLedger(
            user_id=target_user_id,
            entry_kind="admin_topup",
            amount_cents=amount_cents,
            currency=USD,
            related_user_id=admin_user.id,
            note=note,
            meta={"by_admin_user_id": admin_user.id},
        )
        db.add(entry)

        await db.commit()
        await db.refresh(entry)
        return entry

    except Exception:
        await db.rollback()
        raise


async def transfer_to_child(
    db: AsyncSession,
    sender: User,
    child_user: User,
    amount_cents: int,
    note: str | None,
) -> list[WalletLedger]:
    """
    Sender can transfer to DIRECT child only.
    Atomic: sender debit + child credit + ledger entries.
    """
    if child_user.parent_id != sender.id:
        raise ForbiddenTransfer("You can only transfer to your direct child.")

    if amount_cents <= 0:
        raise WalletError("Amount must be positive.")

    tx_id = uuid4()

    try:
        accounts = await _lock_accounts(db, [sender.id, child_user.id])
        sender_acc = accounts[sender.id]
        child_acc = accounts[child_user.id]

        if sender_acc.balance_cents < amount_cents:
            raise InsufficientBalance("Insufficient balance.")

        sender_new = sender_acc.balance_cents - amount_cents
        child_new = child_acc.balance_cents + amount_cents

        await db.execute(
            update(WalletAccount)
            .where(WalletAccount.user_id == sender.id)
            .values(balance_cents=sender_new, updated_at=_now_utc())
        )
        await db.execute(
            update(WalletAccount)
            .where(WalletAccount.user_id == child_user.id)
            .values(balance_cents=child_new, updated_at=_now_utc())
        )

        out_entry = WalletLedger(
            tx_id=tx_id,
            user_id=sender.id,
            entry_kind="transfer_out",
            amount_cents=-amount_cents,
            currency=USD,
            related_user_id=child_user.id,
            note=note,
            meta={"to_user_id": child_user.id},
        )
        in_entry = WalletLedger(
            tx_id=tx_id,
            user_id=child_user.id,
            entry_kind="transfer_in",
            amount_cents=amount_cents,
            currency=USD,
            related_user_id=sender.id,
            note=note,
            meta={"from_user_id": sender.id},
        )

        db.add(out_entry)
        db.add(in_entry)

        await db.commit()
        await db.refresh(out_entry)
        await db.refresh(in_entry)
        return [out_entry, in_entry]

    except Exception:
        await db.rollback()
        raise


async def adjust_child_balance_down(
    db: AsyncSession,
    sender: User,
    child_user: User,
    target_balance_cents: int,
    note: str | None,
) -> list[WalletLedger]:
    """
    Reduce a direct child's balance and return the difference back to sender.

    IMPORTANT: wallet_ledger.entry_kind is constrained by DB check constraint.
    So we record this as a "transfer" from child -> parent using allowed kinds:
    - child: transfer_out (-delta)
    - parent: transfer_in (+delta)
    """
    if child_user.parent_id != sender.id:
        raise ForbiddenTransfer("You can only adjust your direct child.")

    if target_balance_cents < 0:
        raise WalletError("Target balance cannot be negative.")

    tx_id = uuid4()

    try:
        accounts = await _lock_accounts(db, [sender.id, child_user.id])
        sender_acc = accounts[sender.id]
        child_acc = accounts[child_user.id]

        current_child_balance = int(child_acc.balance_cents)

        if target_balance_cents > current_child_balance:
            raise WalletError("Target balance exceeds current balance.")

        delta = current_child_balance - int(target_balance_cents)
        if delta == 0:
            raise WalletError("Target balance equals current balance.")

        # Apply delta: child decreases, sender increases
        child_new = current_child_balance - delta
        sender_new = int(sender_acc.balance_cents) + delta

        await db.execute(
            update(WalletAccount)
            .where(WalletAccount.user_id == child_user.id)
            .values(balance_cents=child_new, updated_at=_now_utc())
        )
        await db.execute(
            update(WalletAccount)
            .where(WalletAccount.user_id == sender.id)
            .values(balance_cents=sender_new, updated_at=_now_utc())
        )

        # Record as transfer child -> parent (allowed entry kinds)
        out_entry = WalletLedger(
            tx_id=tx_id,
            user_id=child_user.id,
            entry_kind="transfer_out",
            amount_cents=-delta,
            currency=USD,
            related_user_id=sender.id,
            note=note,
            meta={
                "kind": "balance_adjustment",
                "to_user_id": sender.id,
                "adjusted_by_user_id": sender.id,
                "target_balance_cents": int(target_balance_cents),
            },
        )
        in_entry = WalletLedger(
            tx_id=tx_id,
            user_id=sender.id,
            entry_kind="transfer_in",
            amount_cents=delta,
            currency=USD,
            related_user_id=child_user.id,
            note=note,
            meta={
                "kind": "balance_adjustment",
                "from_user_id": child_user.id,
                "adjusted_child_user_id": child_user.id,
                "target_balance_cents": int(target_balance_cents),
            },
        )

        db.add(out_entry)
        db.add(in_entry)

        await db.commit()
        await db.refresh(out_entry)
        await db.refresh(in_entry)
        return [out_entry, in_entry]

    except Exception:
        await db.rollback()
        raise



async def admin_adjust_balance(
    db: AsyncSession,
    admin_user: User,
    target_user_id: int,
    amount_cents: int,
    note: str | None,
) -> list[WalletLedger]:
    """
    Admin adjusts a user's balance:
    - amount_cents > 0: admin_topup (entry_kind=admin_topup)
    - amount_cents < 0: record as transfer target -> admin using allowed kinds
      (transfer_out for target, transfer_in for admin)
    Atomic: balance update(s) + ledger insert(s).
    """
    if admin_user.role != "admin":
        raise WalletError("Only admin can adjust balance.")

    if amount_cents == 0:
        raise WalletError("Amount cannot be 0.")

    # Positive: reuse existing logic
    if amount_cents > 0:
        entry = await admin_topup(
            db=db,
            admin_user=admin_user,
            target_user_id=target_user_id,
            amount_cents=amount_cents,
            note=note,
        )
        return [entry]

    # Negative: transfer target -> admin (allowed entry kinds)
    tx_id = uuid4()
    debit = -int(amount_cents)  # positive number to debit from target

    try:
        accounts = await _lock_accounts(db, [target_user_id, int(admin_user.id)])
        target_acc = accounts[target_user_id]
        admin_acc = accounts[int(admin_user.id)]

        if int(target_acc.balance_cents) < debit:
            raise InsufficientBalance("Insufficient balance.")

        target_new = int(target_acc.balance_cents) - debit
        admin_new = int(admin_acc.balance_cents) + debit

        await db.execute(
            update(WalletAccount)
            .where(WalletAccount.user_id == target_user_id)
            .values(balance_cents=target_new, updated_at=_now_utc())
        )
        await db.execute(
            update(WalletAccount)
            .where(WalletAccount.user_id == int(admin_user.id))
            .values(balance_cents=admin_new, updated_at=_now_utc())
        )

        out_entry = WalletLedger(
            tx_id=tx_id,
            user_id=target_user_id,
            entry_kind="transfer_out",
            amount_cents=-debit,
            currency=USD,
            related_user_id=int(admin_user.id),
            note=note,
            meta={
                "kind": "admin_adjustment",
                "by_admin_user_id": int(admin_user.id),
                "to_user_id": int(admin_user.id),
            },
        )
        in_entry = WalletLedger(
            tx_id=tx_id,
            user_id=int(admin_user.id),
            entry_kind="transfer_in",
            amount_cents=debit,
            currency=USD,
            related_user_id=target_user_id,
            note=note,
            meta={
                "kind": "admin_adjustment",
                "by_admin_user_id": int(admin_user.id),
                "from_user_id": target_user_id,
            },
        )

        db.add(out_entry)
        db.add(in_entry)

        await db.commit()
        await db.refresh(out_entry)
        await db.refresh(in_entry)
        return [out_entry, in_entry]

    except Exception:
        await db.rollback()
        raise
async def admin_set_balance_via_parent(
    db: AsyncSession,
    admin_user: User,
    target_user_id: int,
    target_balance_cents: int,
    note: str | None,
) -> list[WalletLedger]:
    """
    Admin sets a user's balance to target_balance_cents by transferring the delta
    between the user's parent and the user.

    If balance increases: parent pays (parent transfer_out, child transfer_in)
    If balance decreases: parent receives (child transfer_out, parent transfer_in)

    Uses only allowed ledger kinds: transfer_out / transfer_in.
    """
    if admin_user.role != "admin":
        raise WalletError("Only admin can set balance.")

    if target_balance_cents < 0:
        raise WalletError("Target balance cannot be negative.")

    # Get target + parent_id
    res = await db.execute(select(User).where(User.id == target_user_id))
    target_user = res.scalar_one_or_none()
    if target_user is None:
        raise WalletError(f"User {target_user_id} not found.")

    if target_user.parent_id is None:
        raise WalletError("Target user has no parent; cannot transfer via parent.")

    parent_id = int(target_user.parent_id)

    tx_id = uuid4()

    try:
        accounts = await _lock_accounts(db, [target_user_id, parent_id])
        child_acc = accounts[target_user_id]
        parent_acc = accounts[parent_id]

        current = int(child_acc.balance_cents)
        target = int(target_balance_cents)

        if target == current:
            raise WalletError("Target balance equals current balance.")

        if target > current:
            # Parent pays child
            delta = target - current

            if int(parent_acc.balance_cents) < delta:
                raise InsufficientBalance("Parent has insufficient balance.")

            parent_new = int(parent_acc.balance_cents) - delta
            child_new = current + delta

            await db.execute(
                update(WalletAccount)
                .where(WalletAccount.user_id == parent_id)
                .values(balance_cents=parent_new, updated_at=_now_utc())
            )
            await db.execute(
                update(WalletAccount)
                .where(WalletAccount.user_id == target_user_id)
                .values(balance_cents=child_new, updated_at=_now_utc())
            )

            parent_entry = WalletLedger(
                tx_id=tx_id,
                user_id=parent_id,
                entry_kind="transfer_out",
                amount_cents=-delta,
                currency=USD,
                related_user_id=target_user_id,
                note=note,
                meta={
                    "kind": "admin_set_balance",
                    "by_admin_user_id": int(admin_user.id),
                    "to_user_id": target_user_id,
                    "target_balance_cents": target,
                },
            )
            child_entry = WalletLedger(
                tx_id=tx_id,
                user_id=target_user_id,
                entry_kind="transfer_in",
                amount_cents=delta,
                currency=USD,
                related_user_id=parent_id,
                note=note,
                meta={
                    "kind": "admin_set_balance",
                    "by_admin_user_id": int(admin_user.id),
                    "from_user_id": parent_id,
                    "target_balance_cents": target,
                },
            )

            db.add(parent_entry)
            db.add(child_entry)

            await db.commit()
            await db.refresh(parent_entry)
            await db.refresh(child_entry)
            return [parent_entry, child_entry]

        else:
            # Child returns to parent
            delta = current - target

            child_new = current - delta
            parent_new = int(parent_acc.balance_cents) + delta

            await db.execute(
                update(WalletAccount)
                .where(WalletAccount.user_id == target_user_id)
                .values(balance_cents=child_new, updated_at=_now_utc())
            )
            await db.execute(
                update(WalletAccount)
                .where(WalletAccount.user_id == parent_id)
                .values(balance_cents=parent_new, updated_at=_now_utc())
            )

            child_entry = WalletLedger(
                tx_id=tx_id,
                user_id=target_user_id,
                entry_kind="transfer_out",
                amount_cents=-delta,
                currency=USD,
                related_user_id=parent_id,
                note=note,
                meta={
                    "kind": "admin_set_balance",
                    "by_admin_user_id": int(admin_user.id),
                    "to_user_id": parent_id,
                    "target_balance_cents": target,
                },
            )
            parent_entry = WalletLedger(
                tx_id=tx_id,
                user_id=parent_id,
                entry_kind="transfer_in",
                amount_cents=delta,
                currency=USD,
                related_user_id=target_user_id,
                note=note,
                meta={
                    "kind": "admin_set_balance",
                    "by_admin_user_id": int(admin_user.id),
                    "from_user_id": target_user_id,
                    "target_balance_cents": target,
                },
            )

            db.add(child_entry)
            db.add(parent_entry)

            await db.commit()
            await db.refresh(child_entry)
            await db.refresh(parent_entry)
            return [child_entry, parent_entry]

    except Exception:
        await db.rollback()
        raise

async def admin_set_balance_via_parent(
    db: AsyncSession,
    admin_user: User,
    target_user_id: int,
    target_balance_cents: int,
    note: str | None,
) -> list[WalletLedger]:
    """
    Admin sets seller balance EXACTLY to target_balance_cents using parent funds.

    If target > current:
      parent transfer_out (-(delta)), child transfer_in (+(delta))

    If target < current:
      child transfer_out (-(delta)), parent transfer_in (+(delta))

    Uses only allowed kinds: transfer_out / transfer_in
    """
    if admin_user.role != "admin":
        raise WalletError("Only admin can set balance.")

    if target_balance_cents < 0:
        raise WalletError("Target balance cannot be negative.")

    # fetch target user
    res = await db.execute(select(User).where(User.id == target_user_id))
    child_user = res.scalar_one_or_none()
    if child_user is None:
        raise WalletError(f"User {target_user_id} not found.")

    if child_user.parent_id is None:
        raise WalletError("Target user has no parent.")

    parent_id = int(child_user.parent_id)

    tx_id = uuid4()

    try:
        accounts = await _lock_accounts(db, [parent_id, int(child_user.id)])
        parent_acc = accounts[parent_id]
        child_acc = accounts[int(child_user.id)]

        current = int(child_acc.balance_cents)
        target = int(target_balance_cents)

        if target == current:
            raise WalletError("Target balance equals current balance.")

        delta = target - current  # + means child needs money, - means child returns money

        entries: list[WalletLedger] = []

        # child needs +delta => parent pays
        if delta > 0:
            if int(parent_acc.balance_cents) < delta:
                raise InsufficientBalance("Parent has insufficient balance.")

            parent_new = int(parent_acc.balance_cents) - delta
            child_new = current + delta

            await db.execute(
                update(WalletAccount)
                .where(WalletAccount.user_id == parent_id)
                .values(balance_cents=parent_new, updated_at=_now_utc())
            )
            await db.execute(
                update(WalletAccount)
                .where(WalletAccount.user_id == int(child_user.id))
                .values(balance_cents=child_new, updated_at=_now_utc())
            )

            parent_entry = WalletLedger(
                tx_id=tx_id,
                user_id=parent_id,
                entry_kind="transfer_out",
                amount_cents=-delta,
                currency=USD,
                related_user_id=int(child_user.id),
                note=note,
                meta={
                    "kind": "admin_set_balance",
                    "direction": "parent_to_child",
                    "child_user_id": int(child_user.id),
                    "target_balance_cents": target,
                    "by_admin_user_id": int(admin_user.id),
                },
            )

            child_entry = WalletLedger(
                tx_id=tx_id,
                user_id=int(child_user.id),
                entry_kind="transfer_in",
                amount_cents=delta,
                currency=USD,
                related_user_id=parent_id,
                note=note,
                meta={
                    "kind": "admin_set_balance",
                    "direction": "parent_to_child",
                    "parent_user_id": parent_id,
                    "target_balance_cents": target,
                    "by_admin_user_id": int(admin_user.id),
                },
            )

            db.add(parent_entry)
            db.add(child_entry)
            entries.extend([parent_entry, child_entry])

        # child returns -delta => parent receives
        else:
            give_back = -delta  # positive

            child_new = current - give_back
            parent_new = int(parent_acc.balance_cents) + give_back

            await db.execute(
                update(WalletAccount)
                .where(WalletAccount.user_id == int(child_user.id))
                .values(balance_cents=child_new, updated_at=_now_utc())
            )
            await db.execute(
                update(WalletAccount)
                .where(WalletAccount.user_id == parent_id)
                .values(balance_cents=parent_new, updated_at=_now_utc())
            )

            child_entry = WalletLedger(
                tx_id=tx_id,
                user_id=int(child_user.id),
                entry_kind="transfer_out",
                amount_cents=-give_back,
                currency=USD,
                related_user_id=parent_id,
                note=note,
                meta={
                    "kind": "admin_set_balance",
                    "direction": "child_to_parent",
                    "parent_user_id": parent_id,
                    "target_balance_cents": target,
                    "by_admin_user_id": int(admin_user.id),
                },
            )

            parent_entry = WalletLedger(
                tx_id=tx_id,
                user_id=parent_id,
                entry_kind="transfer_in",
                amount_cents=give_back,
                currency=USD,
                related_user_id=int(child_user.id),
                note=note,
                meta={
                    "kind": "admin_set_balance",
                    "direction": "child_to_parent",
                    "child_user_id": int(child_user.id),
                    "target_balance_cents": target,
                    "by_admin_user_id": int(admin_user.id),
                },
            )

            db.add(child_entry)
            db.add(parent_entry)
            entries.extend([child_entry, parent_entry])

        await db.commit()
        for e in entries:
            await db.refresh(e)
        return entries

    except Exception:
        await db.rollback()
        raise

async def admin_delete_user_return_balance_to_parent(
    db: AsyncSession,
    admin_user: User,
    target_user_id: int,
    note: str | None,
) -> list[WalletLedger]:
    """
    Delete a user.
    If user has balance > 0: move it to parent FIRST (ledger while user exists), THEN delete.
    Prevents FK error on wallet_ledger.user_id.
    """
    if admin_user.role != "admin":
        raise WalletError("Only admin can delete users.")

    res = await db.execute(select(User).where(User.id == target_user_id))
    target_user = res.scalar_one_or_none()
    if target_user is None:
        raise WalletError("User not found.")

    if target_user.parent_id is None:
        raise WalletError("User has no parent.")

    parent_id = int(target_user.parent_id)
    tx_id = uuid4()

    try:
        accounts = await _lock_accounts(db, [int(target_user.id), parent_id])
        child_acc = accounts[int(target_user.id)]
        parent_acc = accounts[parent_id]

        child_balance = int(child_acc.balance_cents)
        entries: list[WalletLedger] = []

        # ✅ Write ledger BEFORE deleting user
        if child_balance > 0:
            parent_new = int(parent_acc.balance_cents) + child_balance

            await db.execute(
                update(WalletAccount)
                .where(WalletAccount.user_id == parent_id)
                .values(balance_cents=parent_new, updated_at=_now_utc())
            )
            await db.execute(
                update(WalletAccount)
                .where(WalletAccount.user_id == int(target_user.id))
                .values(balance_cents=0, updated_at=_now_utc())
            )

            out_entry = WalletLedger(
                tx_id=tx_id,
                user_id=int(target_user.id),
                entry_kind="transfer_out",
                amount_cents=-child_balance,
                currency=USD,
                related_user_id=parent_id,
                note=note or "Return balance to parent (delete user)",
                meta={
                    "kind": "delete_return_balance",
                    "deleted_user_id": int(target_user.id),
                    "to_user_id": parent_id,
                    "by_admin_user_id": int(admin_user.id),
                },
            )
            in_entry = WalletLedger(
                tx_id=tx_id,
                user_id=parent_id,
                entry_kind="transfer_in",
                amount_cents=child_balance,
                currency=USD,
                related_user_id=int(target_user.id),
                note=note or "Return balance to parent (delete user)",
                meta={
                    "kind": "delete_return_balance",
                    "from_user_id": int(target_user.id),
                    "deleted_user_id": int(target_user.id),
                    "by_admin_user_id": int(admin_user.id),
                },
            )

            db.add(out_entry)
            db.add(in_entry)
            entries.extend([out_entry, in_entry])

            # ✅ flush ensures ledger is inserted while user still exists
            await db.flush()

        # ✅ delete LAST
        await db.delete(target_user)
        await db.commit()

        return entries

    except Exception:
        await db.rollback()
        raise
