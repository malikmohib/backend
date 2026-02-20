from passlib.context import CryptContext

ctx = CryptContext(schemes=["bcrypt"])
hash_ = "$2b$12$vt2zKA39uhSeChvnGn5CMsZXW74gwK7kSphf1aE7IB44PRuSTlxJD58il7o"

print(ctx.verify("admin123", hash_))

