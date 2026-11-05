"""Comprueba que ve un cliente cuando el servidor cierra SIN leer lo que el cliente ya envio (RST) y cuando
cierra de forma limpia con ipad_bridge.close_gracefully(). No abre nada hacia fuera y no escribe archivos.

Uso (en PowerShell, DENTRO de la carpeta del proyecto, donde esta ipad_bridge.py):
    python diagnostico_rst_windows.py
"""
import collections
import os
import platform
import socket
import sys
import threading

sys.path.insert(0, os.getcwd())
try:
    import ipad_bridge
except ImportError:
    print("No encuentro ipad_bridge.py: ejecuta este script dentro de la carpeta del proyecto.")
    sys.exit(1)
if not hasattr(ipad_bridge, "close_gracefully"):
    print("Este ipad_bridge.py aun no tiene close_gracefully (falta aplicar el quinto commit).")
    sys.exit(1)
close_gracefully = ipad_bridge.close_gracefully

REQ = b"GET /api/state HTTP/1.1\r\nHost: x\r\n\r\n"


def servidor(modo):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(64)

    def atender():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            if modo == "abrupto":
                c.close()                       # lo que hacia el puente antes: cerrar sin leer la peticion
            else:
                close_gracefully(c)             # lo que hace ahora
    threading.Thread(target=atender, daemon=True).start()
    return srv


def cliente(puerto):
    s = socket.create_connection(("127.0.0.1", puerto), timeout=3)
    fase = "sendall"
    try:
        s.sendall(REQ)
        fase = "recv"
        return "cierre limpio (b'')" if s.recv(4096) == b"" else "datos inesperados"
    except OSError as e:
        return "%s%s en %s" % (type(e).__name__, " (WinError %s)" % e.winerror if getattr(e, "winerror", None) else "", fase)
    finally:
        s.close()


print("Sistema:", platform.platform(), "| Python", platform.python_version())
for modo, titulo in (("abrupto", "A) Cierre ABRUPTO (comportamiento anterior)"), ("limpio", "B) Cierre LIMPIO (close_gracefully)")):
    srv = servidor(modo)
    res = collections.Counter(cliente(srv.getsockname()[1]) for _ in range(100))
    srv.close()
    print()
    print(titulo, "- 100 intentos:")
    for k, v in res.most_common():
        print("   %3d x %s" % (v, k))
print()
print("Como leerlo: en A) los errores (ConnectionResetError / ConnectionAbortedError) son el RST. En B) deben salir")
print("100 x cierre limpio. Si B) muestra errores, enviame esta salida completa.")
