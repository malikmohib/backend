from app.core.security import hash_password

h = hash_password("admin123")
print(len(h))
print(h)
