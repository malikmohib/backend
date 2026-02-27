from __future__ import annotations

from datetime import datetime
from typing import Iterable
from uuid import uuid4

from sqlalchemy import select, update, delete
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
    Admin adds money into the system for a user (mint). Ledger kind: topup.
    """
    if admin_user.role != "admin":
        raise WalletError("Only admin can top up.")

    if amount_cents <= 0:
        raise WalletError("Amount must be positive.")

    tx_id = uuid4()

    try:
        accounts = await _lock_accounts(db, [target_user_id])
        target_acc = accounts[target_user_id]

        new_bal = int(target_acc.balance_cents) + int(amount_cents)

        await db.execute(
            update(WalletAccount)
            .where(WalletAccount.user_id == target_user_id)
            .values(balance_cents=new_bal, updated_at=_now_utc())
        )

        entry = WalletLedger(
            tx_id=tx_id,
            user_id=target_user_id,
            entry_kind="topup",
            amount_cents=int(amount_cents),
            currency=USD,
            related_user_id=int(admin_user.id),
            note=note or "Admin topup",
            meta={
                "kind": "admin_topup",
                "by_admin_user_id": int(admin_user.id),
            },
        )
        db.add(entry)
        await db.flush()
        return entry

    except Exception:
        raise


async def transfer_between_users(
    db: AsyncSession,
    from_user_id: int,
    to_user_id: int,
    amount_cents: int,
    note: str | None,
    *,
    meta: dict | None = None,
) -> list[WalletLedger]:
    """
    Generic transfer from one user to another with ledger entries.
    """
    if amount_cents <= 0:
        raise WalletError("Amount must be positive.")

    if int(from_user_id) == int(to_user_id):
        raise WalletError("Cannot transfer to same user.")

    tx_id = uuid4()

    accounts = await _lock_accounts(db, [int(from_user_id), int(to_user_id)])
    from_acc = accounts[int(from_user_id)]
    to_acc = accounts[int(to_user_id)]

    if int(from_acc.balance_cents) < int(amount_cents):
        raise InsufficientBalance("Insufficient balance.")

    from_new = int(from_acc.balance_cents) - int(amount_cents)
    to_new = int(to_acc.balance_cents) + int(amount_cents)

    await db.execute(
        update(WalletAccount)
        .where(WalletAccount.user_id == int(from_user_id))
        .values(balance_cents=from_new, updated_at=_now_utc())
    )
    await db.execute(
        update(WalletAccount)
        .where(WalletAccount.user_id == int(to_user_id))
        .values(balance_cents=to_new, updated_at=_now_utc())
    )

    out_entry = WalletLedger(
        tx_id=tx_id,
        user_id=int(from_user_id),
        entry_kind="transfer_out",
        amount_cents=-int(amount_cents),
        currency=USD,
        related_user_id=int(to_user_id),
        note=note or "Transfer out",
        meta=meta or {},
    )
    in_entry = WalletLedger(
        tx_id=tx_id,
        user_id=int(to_user_id),
        entry_kind="transfer_in",
        amount_cents=int(amount_cents),
        currency=USD,
        related_user_id=int(from_user_id),
        note=note or "Transfer in",
        meta=meta or {},
    )

    db.add(out_entry)
    db.add(in_entry)
    await db.flush()

    return [out_entry, in_entry]


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

            out_entry = WalletLedger(
                tx_id=tx_id,
                user_id=parent_id,
                entry_kind="transfer_out",
                amount_cents=-delta,
                currency=USD,
                related_user_id=target_user_id,
                note=note or "Set balance via parent",
                meta={
                    "kind": "admin_set_balance_via_parent",
                    "by_admin_user_id": int(admin_user.id),
                    "child_user_id": int(target_user_id),
                },
            )
            in_entry = WalletLedger(
                tx_id=tx_id,
                user_id=target_user_id,
                entry_kind="transfer_in",
                amount_cents=delta,
                currency=USD,
                related_user_id=parent_id,
                note=note or "Set balance via parent",
                meta={
                    "kind": "admin_set_balance_via_parent",
                    "by_admin_user_id": int(admin_user.id),
                    "parent_user_id": parent_id,
                },
            )
            db.add(out_entry)
            db.add(in_entry)
            await db.flush()
            return [out_entry, in_entry]

        # target < current: child pays parent
        delta = current - target

        parent_new = int(parent_acc.balance_cents) + delta
        child_new = current - delta

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

        out_entry = WalletLedger(
            tx_id=tx_id,
            user_id=target_user_id,
            entry_kind="transfer_out",
            amount_cents=-delta,
            currency=USD,
            related_user_id=parent_id,
            note=note or "Set balance via parent",
            meta={
                "kind": "admin_set_balance_via_parent",
                "by_admin_user_id": int(admin_user.id),
                "to_parent_user_id": parent_id,
            },
        )
        in_entry = WalletLedger(
            tx_id=tx_id,
            user_id=parent_id,
            entry_kind="transfer_in",
            amount_cents=delta,
            currency=USD,
            related_user_id=target_user_id,
            note=note or "Set balance via parent",
            meta={
                "kind": "admin_set_balance_via_parent",
                "by_admin_user_id": int(admin_user.id),
                "from_child_user_id": int(target_user_id),
            },
        )
        db.add(out_entry)
        db.add(in_entry)
        await db.flush()
        return [out_entry, in_entry]

    except Exception:
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
                    "deleted_user_id": int(target_user.id),
                    "to_user_id": parent_id,
                    "by_admin_user_id": int(admin_user.id),
                },
            )
            db.add(out_entry)
            db.add(in_entry)
            await db.flush()

            entries.extend([out_entry, in_entry])

        # ✅ Delete related wallet account and user
        await db.execute(delete(WalletAccount).where(WalletAccount.user_id == int(target_user.id)))
        await db.execute(delete(User).where(User.id == int(target_user.id)))

        return entries

    except Exception:
        raise


# -----------------------------
# ✅ SELLER-scoped variants
# -----------------------------

async def seller_set_balance_via_parent(
    db: AsyncSession,
    seller_user: User,
    target_user_id: int,
    target_balance_cents: int,
    note: str | None,
) -> list[WalletLedger]:
    """
    Seller sets direct child seller balance by transferring delta between seller and child.

    Permission:
    - seller_user.role must be 'seller'
    - target_user.parent_id must equal seller_user.id
    """
    if seller_user.role != "seller":
        raise WalletError("Only seller can set balance here.")

    if target_balance_cents < 0:
        raise WalletError("Target balance cannot be negative.")

    res = await db.execute(select(User).where(User.id == int(target_user_id)))
    target_user = res.scalar_one_or_none()
    if target_user is None:
        raise WalletError("User not found.")

    if target_user.parent_id is None or int(target_user.parent_id) != int(seller_user.id):
        raise WalletError("Forbidden: can only set balance for direct children.")

    parent_id = int(seller_user.id)
    tx_id = uuid4()

    accounts = await _lock_accounts(db, [int(target_user_id), parent_id])
    child_acc = accounts[int(target_user_id)]
    parent_acc = accounts[parent_id]

    current = int(child_acc.balance_cents)
    target = int(target_balance_cents)

    if target == current:
        raise WalletError("Target balance equals current balance.")

    if target > current:
        # Seller pays child
        delta = target - current

        if int(parent_acc.balance_cents) < delta:
            raise InsufficientBalance("Insufficient seller balance.")

        parent_new = int(parent_acc.balance_cents) - delta
        child_new = current + delta

        await db.execute(
            update(WalletAccount)
            .where(WalletAccount.user_id == parent_id)
            .values(balance_cents=parent_new, updated_at=_now_utc())
        )
        await db.execute(
            update(WalletAccount)
            .where(WalletAccount.user_id == int(target_user_id))
            .values(balance_cents=child_new, updated_at=_now_utc())
        )

        out_entry = WalletLedger(
            tx_id=tx_id,
            user_id=parent_id,
            entry_kind="transfer_out",
            amount_cents=-delta,
            currency=USD,
            related_user_id=int(target_user_id),
            note=note or "Set balance via parent",
            meta={
                "kind": "seller_set_balance_via_parent",
                "by_seller_user_id": int(seller_user.id),
                "child_user_id": int(target_user_id),
            },
        )
        in_entry = WalletLedger(
            tx_id=tx_id,
            user_id=int(target_user_id),
            entry_kind="transfer_in",
            amount_cents=delta,
            currency=USD,
            related_user_id=parent_id,
            note=note or "Set balance via parent",
            meta={
                "kind": "seller_set_balance_via_parent",
                "by_seller_user_id": int(seller_user.id),
                "parent_user_id": parent_id,
            },
        )
        db.add(out_entry)
        db.add(in_entry)
        await db.flush()
        return [out_entry, in_entry]

    # target < current: child pays seller
    delta = current - target

    parent_new = int(parent_acc.balance_cents) + delta
    child_new = current - delta

    await db.execute(
        update(WalletAccount)
        .where(WalletAccount.user_id == parent_id)
        .values(balance_cents=parent_new, updated_at=_now_utc())
    )
    await db.execute(
        update(WalletAccount)
        .where(WalletAccount.user_id == int(target_user_id))
        .values(balance_cents=child_new, updated_at=_now_utc())
    )

    out_entry = WalletLedger(
        tx_id=tx_id,
        user_id=int(target_user_id),
        entry_kind="transfer_out",
        amount_cents=-delta,
        currency=USD,
        related_user_id=parent_id,
        note=note or "Set balance via parent",
        meta={
            "kind": "seller_set_balance_via_parent",
            "by_seller_user_id": int(seller_user.id),
            "to_parent_user_id": parent_id,
        },
    )
    in_entry = WalletLedger(
        tx_id=tx_id,
        user_id=parent_id,
        entry_kind="transfer_in",
        amount_cents=delta,
        currency=USD,
        related_user_id=int(target_user_id),
        note=note or "Set balance via parent",
        meta={
            "kind": "seller_set_balance_via_parent",
            "by_seller_user_id": int(seller_user.id),
            "from_child_user_id": int(target_user_id),
        },
    )
    db.add(out_entry)
    db.add(in_entry)
    await db.flush()
    return [out_entry, in_entry]


async def seller_delete_user_return_balance_to_parent(
    db: AsyncSession,
    seller_user: User,
    target_user_id: int,
    note: str | None,
) -> list[WalletLedger]:
    """
    Seller "deletes" a direct child user.

    New behavior (SAFE for finance + matches your requirement):
    - If target has children OR orders: deactivate target + all descendants (subtree)
    - Return ALL balances from subtree users to the seller (owner) with ledger entries
    - Never hard-delete users (avoids FK violations with orders / ledger)

    Permission:
    - seller_user.role must be 'seller'
    - target_user.parent_id must equal seller_user.id (direct child)
    """
    if seller_user.role != "seller":
        raise WalletError("Only seller can delete users here.")

    # Load target user
    res = await db.execute(select(User).where(User.id == int(target_user_id)))
    target_user = res.scalar_one_or_none()
    if target_user is None:
        raise WalletError("User not found.")

    # Must be direct child
    if target_user.parent_id is None or int(target_user.parent_id) != int(seller_user.id):
        raise WalletError("Forbidden: can only delete direct children.")

    owner_id = int(seller_user.id)

    # --- 1) Compute subtree user ids (target + descendants) ---
    # Using ltree: descendants have path that is contained by target_user.path
    # (child.path is descendant of target.path)
    # Note: in ltree, "descendant <@ ancestor" is true.
    subtree_res = await db.execute(
        select(User.id).where(User.path.op("<@")(target_user.path))
    )
    subtree_ids = [int(r[0]) for r in subtree_res.all()]

    # Safety: ensure target included
    if int(target_user.id) not in subtree_ids:
        subtree_ids.append(int(target_user.id))

    # --- 2) Lock all wallets involved (subtree + owner) ---
    accounts = await _lock_accounts(db, [owner_id, *subtree_ids])
    owner_acc = accounts[owner_id]

    tx_id = uuid4()
    entries: list[WalletLedger] = []

    # --- 3) Move balances from each subtree user -> owner ---
    # Use transfer_out/transfer_in so tx_id sums to 0.
    for uid in subtree_ids:
        if uid == owner_id:
            continue

        acc = accounts.get(uid)
        if not acc:
            continue

        bal = int(acc.balance_cents)
        if bal <= 0:
            continue

        # update balances
        owner_new = int(owner_acc.balance_cents) + bal
        await db.execute(
            update(WalletAccount)
            .where(WalletAccount.user_id == owner_id)
            .values(balance_cents=owner_new, updated_at=_now_utc())
        )
        await db.execute(
            update(WalletAccount)
            .where(WalletAccount.user_id == uid)
            .values(balance_cents=0, updated_at=_now_utc())
        )

        # keep local object in sync for subsequent iterations
        owner_acc.balance_cents = owner_new
        acc.balance_cents = 0

        out_entry = WalletLedger(
            tx_id=tx_id,
            user_id=uid,
            entry_kind="transfer_out",
            amount_cents=-bal,
            currency=USD,
            related_user_id=owner_id,
            note=note or "Deactivate subtree: return balance to owner",
            meta={
                "kind": "seller_deactivate_subtree_return_balance",
                "root_deleted_user_id": int(target_user.id),
                "from_user_id": uid,
                "to_owner_user_id": owner_id,
                "by_seller_user_id": owner_id,
            },
        )
        in_entry = WalletLedger(
            tx_id=tx_id,
            user_id=owner_id,
            entry_kind="transfer_in",
            amount_cents=bal,
            currency=USD,
            related_user_id=uid,
            note=note or "Deactivate subtree: receive balance from user",
            meta={
                "kind": "seller_deactivate_subtree_return_balance",
                "root_deleted_user_id": int(target_user.id),
                "from_user_id": uid,
                "to_owner_user_id": owner_id,
                "by_seller_user_id": owner_id,
            },
        )
        db.add(out_entry)
        db.add(in_entry)
        await db.flush()

        entries.extend([out_entry, in_entry])

    # --- 4) Deactivate all subtree users (including target) ---
    await db.execute(
    update(User)
    .where(User.id.in_(subtree_ids))
    .values(is_active=False)
   )

    # NOTE: We do NOT delete users or wallet_accounts to avoid FK violations
    # with orders and to preserve audit history.

    return entries


# -------------------------------------------------------
# ✅ BACKWARD-COMPATIBILITY HELPERS (required by seller_wallet)
# -------------------------------------------------------

async def adjust_child_balance_up(
    db: AsyncSession,
    parent_user: User,
    child_user_id: int,
    amount_cents: int,
    note: str | None = None,
) -> list[WalletLedger]:
    """
    Legacy helper expected by existing routers:
    Increase child's balance by transferring FROM parent -> child.

    Safety:
    - locks both accounts FOR UPDATE
    - checks parent has enough balance
    - writes wallet_ledger entries
    - enforces direct parent relationship
    """
    if amount_cents <= 0:
        raise WalletError("Amount must be positive.")

    res = await db.execute(select(User).where(User.id == int(child_user_id)))
    child = res.scalar_one_or_none()
    if child is None:
        raise WalletError("User not found.")

    if child.parent_id is None or int(child.parent_id) != int(parent_user.id):
        raise WalletError("Forbidden: can only adjust balance for direct children.")

    return await transfer_between_users(
        db=db,
        from_user_id=int(parent_user.id),
        to_user_id=int(child_user_id),
        amount_cents=int(amount_cents),
        note=note or "Adjust child balance up",
        meta={
            "kind": "adjust_child_balance_up",
            "parent_user_id": int(parent_user.id),
            "child_user_id": int(child_user_id),
        },
    )


async def adjust_child_balance_down(
    db: AsyncSession,
    parent_user: User,
    child_user_id: int,
    amount_cents: int,
    note: str | None = None,
) -> list[WalletLedger]:
    """
    Legacy helper expected by existing routers:
    Decrease child's balance by transferring FROM child -> parent.

    Safety:
    - locks both accounts FOR UPDATE
    - checks child has enough balance
    - writes wallet_ledger entries
    - enforces direct parent relationship
    """
    if amount_cents <= 0:
        raise WalletError("Amount must be positive.")

    res = await db.execute(select(User).where(User.id == int(child_user_id)))
    child = res.scalar_one_or_none()
    if child is None:
        raise WalletError("User not found.")

    if child.parent_id is None or int(child.parent_id) != int(parent_user.id):
        raise WalletError("Forbidden: can only adjust balance for direct children.")

    return await transfer_between_users(
        db=db,
        from_user_id=int(child_user_id),
        to_user_id=int(parent_user.id),
        amount_cents=int(amount_cents),
        note=note or "Adjust child balance down",
        meta={
            "kind": "adjust_child_balance_down",
            "parent_user_id": int(parent_user.id),
            "child_user_id": int(child_user_id),
        },
    )
async def transfer_to_child(
    db: AsyncSession,
    parent_user: User,
    child_user_id: int,
    amount_cents: int,
    note: str | None = None,
) -> list[WalletLedger]:
    """
    Legacy helper expected by seller_wallet.
    Transfer from parent -> direct child with ledger + row locks.
    """
    if amount_cents <= 0:
        raise WalletError("Amount must be positive.")

    res = await db.execute(select(User).where(User.id == int(child_user_id)))
    child = res.scalar_one_or_none()
    if child is None:
        raise WalletError("User not found.")

    if child.parent_id is None or int(child.parent_id) != int(parent_user.id):
        raise WalletError("Forbidden: can only transfer to direct children.")

    return await transfer_between_users(
        db=db,
        from_user_id=int(parent_user.id),
        to_user_id=int(child_user_id),
        amount_cents=int(amount_cents),
        note=note or "Transfer to child",
        meta={
            "kind": "transfer_to_child",
            "parent_user_id": int(parent_user.id),
            "child_user_id": int(child_user_id),
        },
    )


async def transfer_from_child(
    db: AsyncSession,
    parent_user: User,
    child_user_id: int,
    amount_cents: int,
    note: str | None = None,
) -> list[WalletLedger]:
    """
    Legacy helper expected by seller_wallet (often paired with transfer_to_child).
    Transfer from direct child -> parent with ledger + row locks.
    """
    if amount_cents <= 0:
        raise WalletError("Amount must be positive.")

    res = await db.execute(select(User).where(User.id == int(child_user_id)))
    child = res.scalar_one_or_none()
    if child is None:
        raise WalletError("User not found.")

    if child.parent_id is None or int(child.parent_id) != int(parent_user.id):
        raise WalletError("Forbidden: can only transfer from direct children.")

    return await transfer_between_users(
        db=db,
        from_user_id=int(child_user_id),
        to_user_id=int(parent_user.id),
        amount_cents=int(amount_cents),
        note=note or "Transfer from child",
        meta={
            "kind": "transfer_from_child",
            "parent_user_id": int(parent_user.id),
            "child_user_id": int(child_user_id),
        },
    )