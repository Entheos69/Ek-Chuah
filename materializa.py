"""
materializa.py -- El brazo LOCAL de la puerta sancionada (flujo nace-en-la-nube).

El Estratega (nube) investiga y SANCIONA la entrada; este materializador, local, aterriza
lo ya sancionado en el durable AEC: snapshot content-addressed (la roca baja) + cadena de
via + inscripcion + afirmacion pinneada a la version (I4).

NO decide que entra (eso es del Estratega); solo materializa lo sancionado. El gatillo de
la necesidad lleva el sello de quien sanciono ('explicito' del Guardian | 'implicito-de:'
del Estratega) -> accountability D2 sin maquinaria nueva.

Solo stdlib.
"""
from __future__ import annotations
from nucleo import Inscripcion
from via_epistemica import ViaEmision


class Materializador:
    def __init__(self, store):
        self.store = store
        self.via = ViaEmision(store)

    def materializar(self, *, pregunta: str, gatillo: str, formulacion: str,
                     url: str, snapshot_bytes: bytes, inscripcion: Inscripcion,
                     origen_nodo: str = None, fecha_fuente: str = "capture",
                     tipo: str = "claim", estatus: str = "afirmado",
                     txt: str = None) -> dict:
        """Aterriza una solicitud de materializacion YA SANCIONADA. Orden fijo:
        snapshot -> necesidad -> consulta -> referencia(version) -> inscripcion -> afirmacion.
        La afirmacion queda anclada a la VERSION (content-hash), nunca al referente (I4)."""
        if not inscripcion.invariante_ok():
            raise ValueError("INVARIANTE VIOLADO: la inscripcion no trae su tripleta.")
        h = self.store.put_snapshot(snapshot_bytes)          # la roca baja al durable local
        nec = self.via.necesidad(pregunta, gatillo, origen_nodo)
        q = self.via.consulta(nec, formulacion)
        ref = self.via.referencia(q, url, h, fecha_fuente=fecha_fuente)
        insc = self.via.inscripcion(inscripcion)
        af = self.via.afirmacion(txt or inscripcion.conclusion, insc, ref, tipo, estatus)
        return {"snapshot": h, "necesidad": nec, "consulta": q,
                "referencia": ref, "inscripcion": insc, "afirmacion": af}
