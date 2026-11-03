"""Gestor multi-IA de BunnyLoL (etapa 2).

Módulos:
  keystore   claves API en el Administrador de credenciales de Windows (con respaldo en archivo)
  health     estado, tiempos de espera y contadores de cada proveedor
  providers  catálogo de proveedores y un adaptador por proveedor (identidad, estado, validación)
  consensus  fusión de varias respuestas validadas, conservando quién aportó qué
  manager    ProviderManager: configuración, orden, estrategia por modo (rápido/completo)

Se importa de forma perezosa desde backend/aiadvisor.py: si algo falla aquí, el motor matemático
y la IA de un solo proveedor siguen funcionando como antes.
"""
