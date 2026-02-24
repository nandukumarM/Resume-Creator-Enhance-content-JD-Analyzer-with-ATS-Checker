try:
    import werkzeug.security as ws
    print(f"Werkzeug Security imported successfully.")
    
    password = "testpassword"
    
    if hasattr(ws, 'generate_password_hash'):
        hashed = ws.generate_password_hash(password)
        print(f"Hash generated: {hashed}")
        
        if hasattr(ws, 'check_password_hash'):
            is_valid = ws.check_password_hash(hashed, password)
            print(f"Password check result: {is_valid}")
        else:
            print("check_password_hash not found")
            
    else:
        print("generate_password_hash not found")

except ImportError as e:
    print(f"ImportError: {e}")
except Exception as e:
    print(f"Error: {e}")
