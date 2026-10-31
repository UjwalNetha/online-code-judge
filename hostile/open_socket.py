import socket

connection = socket.create_connection(("1.1.1.1", 80), timeout=2)
print(connection)
