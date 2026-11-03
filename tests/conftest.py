"""Configuración común de las pruebas.

Varios módulos de test llaman a `ddragon.warmup()` al importarse. Eso lanza un hilo
en segundo plano que carga el catálogo real (desde cache/) y, al terminar, SUSTITUYE
`ddragon.items` y ejecuta `selfcheck.run()`. Si ese hilo acaba en mitad de otro test
(que ha puesto un catálogo falso), el resultado dependía del azar: tests que fallaban
una de cada dos ejecuciones sin que el código de producción hubiera cambiado.

Aquí se espera a que terminen esos hilos ANTES de ejecutar ninguna prueba, de modo
que la suite sea determinista. No se salta ni se debilita ningún test.
"""
import threading
import time


def pytest_collection_finish(session):
    deadline = time.time() + 120
    me = threading.current_thread()
    while time.time() < deadline:
        busy = [t for t in threading.enumerate()
                if t is not me and t.daemon and t.is_alive()]
        if not busy:
            return
        time.sleep(0.1)
