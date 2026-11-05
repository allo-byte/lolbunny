"""Mide cuanto tarda el sistema en rechazar una conexion a un puerto CERRADO de 127.0.0.1.
No usa el puente ni nada del proyecto, no escribe archivos y no abre nada hacia fuera.

Uso (en PowerShell):   python diagnostico_conexion_windows.py
"""
import platform
import socket
import time


def puerto_cerrado():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()                       # queda cerrado: nadie escucha
    return p


def medir(puerto, tope):
    t = time.time()
    try:
        socket.create_connection(("127.0.0.1", puerto), timeout=tope).close()
        res = "CONECTO"
    except OSError as e:
        res = type(e).__name__
    return time.time() - t, res


print("Sistema:", platform.platform(), "| Python", platform.python_version())
print()
print("A) Puerto cerrado, tope 5 s (como el puente ANTES del cambio):")
for _ in range(3):
    dt, res = medir(puerto_cerrado(), 5.0)
    print("   %.3f s  -> %s" % (dt, res))

print("B) Puerto cerrado, tope 1.5 s (como el puente DESPUES del cambio):")
for _ in range(3):
    dt, res = medir(puerto_cerrado(), 1.5)
    print("   %.3f s  -> %s" % (dt, res))

srv = socket.socket()
srv.bind(("127.0.0.1", 0))
srv.listen(5)
print("C) Control: puerto ABIERTO (debe ser casi instantaneo):")
for _ in range(3):
    dt, res = medir(srv.getsockname()[1], 5.0)
    print("   %.4f s  -> %s" % (dt, res))
srv.close()

print()
print("Como leerlo: si en A) sale ~2 s (ConnectionRefusedError) y en C) ~0 s, el retraso lo pone Windows")
print("al rechazar conexiones, no el codigo del puente. En B) debe salir ~1.5 s (TimeoutError).")
