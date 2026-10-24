"""Puente para ver el overlay de LoL Build Advisor desde el iPad.

Reenvía el puerto de la red local (0.0.0.0:PUERTO_PUENTE) al servidor
de la app (127.0.0.1:PUERTO_APP), sin tocar el código de la app.
Ejecútalo en el PC mientras app.py está abierto.
"""
import socket
import sys
import threading

PUERTO_APP = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
PUERTO_PUENTE = int(sys.argv[2]) if len(sys.argv) > 2 else 8766


def ip_local():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no envía nada, solo elige la interfaz
        return s.getsockname()[0]
    except Exception:
        return "TU-IP-LOCAL"
    finally:
        s.close()


def copiar(origen, destino):
    try:
        while True:
            datos = origen.recv(65536)
            if not datos:
                break
            destino.sendall(datos)
    except OSError:
        pass
    finally:
        for s in (origen, destino):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            s.close()


def atender(cliente):
    try:
        app = socket.create_connection(("127.0.0.1", PUERTO_APP), timeout=5)
        app.settimeout(None)
    except OSError:
        cliente.close()
        return
    threading.Thread(target=copiar, args=(cliente, app), daemon=True).start()
    threading.Thread(target=copiar, args=(app, cliente), daemon=True).start()


def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", PUERTO_PUENTE))
    srv.listen(20)
    ip = ip_local()
    print("=" * 52)
    print("  Puente iPad activo")
    print(f"  En el iPad (misma Wi-Fi) abre:")
    print(f"    http://{ip}:{PUERTO_PUENTE}/overlay")
    print(f"    http://{ip}:{PUERTO_PUENTE}/   (analizador)")
    print("  Si la IP cambia al reiniciar el router, prueba con el nombre:")
    print(f"    http://{socket.gethostname()}.local:{PUERTO_PUENTE}/overlay")
    print("  Ctrl+C para cerrar")
    print("=" * 52)
    while True:
        c, _ = srv.accept()
        threading.Thread(target=atender, args=(c,), daemon=True).start()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
