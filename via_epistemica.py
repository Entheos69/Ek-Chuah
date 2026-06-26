"""
via_epistemica.py -- La cadena causal del saber exterior (lado EMISION, forma Q).

    necesidad --(consulta)--> referencia(version) --(survived_from)--> afirmacion

Cada metodo EMITE un evento al log durable (aec_store). NO consulta: el lado lectura
(traza, huerfanos, version_actual) vive en proyeccion.py sobre la .db regenerable (CQRS).

I4: la referencia separa REFERENTE (canonical URL, identidad persistente) de VERSION
(content-hash). La afirmacion se ancla al id de una referencia = una VERSION concreta,
nunca al referente mutable. fecha_fuente con trust-order web (capture = confiable).

D2 / accountability: el gatillo de la necesidad graba quien sanciono la entrada
('explicito' del Guardian | 'implicito-de:<orden>' del Estratega).

Solo stdlib.
"""
from __future__ import annotations
import uuid
import datetime
from nucleo import ISO, Inscripcion
from normaliza_url import referente_id


def _id() -> str:
    return uuid.uuid4().hex


class ViaEmision:
    def __init__(self, store):
        self.store = store

    def necesidad(self, pregunta: str, gatillo: str, origen_nodo=None) -> str:
        nid = _id()
        self.store.append_event({"ev": "necesidad", "id": nid, "pregunta": pregunta,
                                 "gatillo": gatillo, "origen_nodo": origen_nodo})
        return nid

    def consulta(self, nec_id: str, formulacion: str) -> str:
        qid = _id()
        self.store.append_event({"ev": "consulta", "id": qid, "nec_id": nec_id,
                                 "formulacion": formulacion})
        return qid

    def referencia(self, q_id: str, url_cruda: str, content_hash: str,
                   capture_ts: str = None, fecha_fuente: str = "capture") -> str:
        """Una VERSION de un referente. content_hash = identidad de la roca capturada.
        fecha_fuente='capture' (confiable) por defecto; 'contenido' si viene del documento."""
        rid = _id()
        self.store.append_event({
            "ev": "referencia", "id": rid, "q_id": q_id,
            "url_cruda": url_cruda, "referente_id": referente_id(url_cruda),
            "content_hash": content_hash,
            "capture_ts": capture_ts or datetime.datetime.now().strftime(ISO),
            "fecha_fuente": fecha_fuente})
        return rid

    def inscripcion(self, ins: Inscripcion) -> str:
        if not ins.invariante_ok():
            raise ValueError("INVARIANTE VIOLADO: conclusion sin premisa/busqueda/resultados.")
        ev = ins.to_event()
        ev["id"] = _id()
        self.store.append_event(ev)
        return ev["id"]

    def afirmacion(self, txt: str, insc_id: str, ref_id: str = None,
                   tipo: str = "claim", estatus: str = "afirmado") -> str:
        """ref_id apunta a una REFERENCIA (= version pinneada), no a un referente."""
        aid = _id()
        self.store.append_event({"ev": "afirmacion", "id": aid, "txt": txt,
                                 "insc_id": insc_id, "ref_id": ref_id,
                                 "tipo": tipo, "estatus": estatus})
        return aid

    def referente_assert(self, referente_a: str, referente_b: str,
                         relacion: str, gatillo: str) -> str:
        """Override gobernado D-ver-1: aseverar ref A == ref B (mirror) o split.
        Append-only y auditado por gatillo. NO fusiona destructivamente: las versiones
        y lecturas se conservan (Forma-vs-Valor)."""
        sid = _id()
        self.store.append_event({"ev": "referente_assert", "id": sid,
                                 "referente_a": referente_a, "referente_b": referente_b,
                                 "relacion": relacion, "gatillo": gatillo})
        return sid
