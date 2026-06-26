"""
nucleo.py -- La capa de inscripcion (substrato greenfield, forma Q).

    Premisa(t) ~= Busqueda(t) + Resultados(t)   para toda inferencia(t), inamovible (t+n)

Una inferencia es LECTURA fechada y firmada por su inferidor(t, model), no un hecho. Lo
durable (la roca) son los TRES insumos: premisa, busqueda, resultados_crudos. La conclusion
es re-derivable.

En la forma Q (event-sourcing), el durable es el LOG append-only (aec_store), NO SQLite.
Aqui viven las estructuras + su serializacion a evento. La proyeccion SQLite se reconstruye
del log (proyeccion.py) y es desechable.

Solo stdlib. Sin emojis (encoding Windows).
"""
from __future__ import annotations
import json
import hashlib
import datetime
from dataclasses import dataclass, field

ISO = "%Y-%m-%dT%H:%M:%S"


def _canon(obj) -> str:
    """Serializacion canonica y estable: misma roca -> misma cadena -> misma huella."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def huella_insumos(premisa: str, busqueda: list, resultados_crudos: list) -> str:
    """sha256 sobre los TRES insumos = identidad de la roca."""
    roca = {"premisa": premisa, "busqueda": busqueda, "resultados_crudos": resultados_crudos}
    return hashlib.sha256(_canon(roca).encode("utf-8")).hexdigest()


def content_hash(data: bytes) -> str:
    """sha256 del contenido crudo = identidad de la VERSION (I4)."""
    return hashlib.sha256(data).hexdigest()


@dataclass
class Inferidor:
    """Quien infiere. No es un sujeto continuo; es un modelo fechado y firmado."""
    model: str
    ts: str = field(default_factory=lambda: datetime.datetime.now().strftime(ISO))

    def firma(self) -> str:
        return f"{self.model}@{self.ts}"


@dataclass
class Inscripcion:
    premisa: str
    busqueda: list
    resultados_crudos: list
    conclusion: str
    inferidor: Inferidor
    huella: str = ""

    def __post_init__(self):
        if not self.huella:
            self.huella = huella_insumos(self.premisa, self.busqueda, self.resultados_crudos)

    def invariante_ok(self) -> bool:
        """Premisa ~= Busqueda + Resultados: no hay conclusion-roca sin sus tres insumos."""
        return (bool(self.premisa.strip())
                and len(self.busqueda) > 0
                and len(self.resultados_crudos) > 0)

    def integridad_ok(self) -> bool:
        """La roca no fue alterada entre t y t+n: recomputar la huella y comparar."""
        return self.huella == huella_insumos(self.premisa, self.busqueda, self.resultados_crudos)

    def to_event(self) -> dict:
        """Serializa a evento de log (forma Q). El durable es esta linea, no una fila SQLite."""
        return {
            "ev": "inscripcion",
            "premisa": self.premisa,
            "busqueda": self.busqueda,
            "resultados_crudos": self.resultados_crudos,
            "conclusion": self.conclusion,
            "inferidor_model": self.inferidor.model,
            "inferidor_ts": self.inferidor.ts,
            "huella": self.huella,
        }


def reinferir(ins: Inscripcion, inferidor_fn, model: str) -> Inscripcion:
    """Los MISMOS tres insumos por un inferidor distinto. Misma huella, otra conclusion."""
    nueva = inferidor_fn(ins.premisa, ins.busqueda, ins.resultados_crudos)
    return Inscripcion(ins.premisa, ins.busqueda, ins.resultados_crudos, nueva, Inferidor(model))


def divergencia(a: Inscripcion, b: Inscripcion) -> dict:
    """Cuanto difieren dos lecturas de la MISMA roca. Huellas distintas => no comparable."""
    if a.huella != b.huella:
        raise ValueError("Huellas distintas: divergencia de insumo, no de inferidor. No comparable.")
    ta = set(a.conclusion.lower().split())
    tb = set(b.conclusion.lower().split())
    union = ta | tb
    jac = len(ta & tb) / len(union) if union else 1.0
    return {"huella": a.huella[:12], "similitud": round(jac, 3), "divergencia": round(1 - jac, 3)}
