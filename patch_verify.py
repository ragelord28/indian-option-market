with open("scripts/verify_auth_bot_flow.py", "r") as f:
    content = f.read()

old_code = """    # Check if process is listening on 8501
    import time
    time.sleep(5)
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    res = sock.connect_ex(('127.0.0.1', 8501))
    sock.close()
    assert res == 0, "OAuth listener did not start on port 8501"
    print("Listener successfully spawned on port 8501!")"""

new_code = """    # Check if process is listening on 8501
    import time
    import socket
    res = -1
    for i in range(15):
        time.sleep(1)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        res = sock.connect_ex(('127.0.0.1', 8501))
        sock.close()
        if res == 0:
            break
    assert res == 0, "OAuth listener did not start on port 8501"
    print("Listener successfully spawned on port 8501!")"""

content = content.replace(old_code, new_code)
with open("scripts/verify_auth_bot_flow.py", "w") as f:
    f.write(content)
print("patched")
