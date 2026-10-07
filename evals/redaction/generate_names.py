"""Builds the labelled name sets for redaction (EF-06, ADR-0004 §2).

- names.jsonl (development): used to choose the model and to design the filters.
- names_validation.jsonl: other phrasings and other name pools, written before any measurement
  on it and never used for tuning. The recall floor of ADR-0004 comes from this set only.

Every name is invented by combining common Peruvian first names and surnames; no message comes
from a real person. The output is deterministic, so the files can be regenerated and diffed:

    python evals/redaction/generate_names.py
"""

import json
import random
import unicodedata
from pathlib import Path

SEED = 2026
VARIANTS = 7
OUTPUT = Path(__file__).with_name("names.jsonl")
VALIDATION_SEED = 1821
VALIDATION_VARIANTS = 6
VALIDATION_OUTPUT = Path(__file__).with_name("names_validation.jsonl")

FIRST = [
    "Rosa", "Luis", "Carmen", "Jorge", "María", "José", "Ana", "Juan", "Pedro", "Lucía",
    "Milagros", "Yolanda", "Wilber", "Edwin", "Nilda", "Gladys", "Fiorella", "Brayan", "Kelly",
    "Yessenia", "Elvis", "Percy", "Rocío", "Teófilo", "Feliciano", "Juana", "Hilda", "Marleny",
    "Alexander", "Dayana", "Ronald", "Maritza", "Nancy", "Wilfredo", "Sonia", "Héctor", "Raúl",
    "Jhonatan", "Yeny", "Gonzalo",
]  # fmt: skip
SURNAMES = [
    "Quispe", "Mamani", "Huamán", "Condori", "Ccori", "Apaza", "Ticona", "Huanca", "Choque",
    "Cusi", "Paucar", "Yupanqui", "Ccahuana", "Chávez", "Rodríguez", "Sánchez", "Vásquez",
    "Rojas", "Díaz", "García", "Gutiérrez", "Villanueva", "Castillo", "Espinoza", "Salazar",
    "Cárdenas", "Palomino", "Zevallos", "De la Cruz", "Del Águila",
]  # fmt: skip
NICKNAMES = ["Lucho", "Pepe", "Charo", "Chabuca", "Toño", "Kike", "Mile", "Pochita"]

# (template, brands mentioned). Name slots: {first}, {first2}, {surname}, {full}, {full2},
# {nick}, {first_lower}, {first2_lower}, {full_plain} (no accents).
NAME_TEMPLATES: list[tuple[str, list[str]]] = [
    ("Hola mamá, soy {first}, cambié de número. No le digas a nadie, necesito que me yapees urgente.", []),
    ("Tía, soy tu sobrino {first}, tuve un accidente y estoy en la comisaría. Yapéame S/ 800 a este número.", []),
    ("Abuelita, soy {full}, me robaron el celular. Deposítale a mi amigo {first2} que te va a escribir.", []),
    ("Hola, soy {full} del área de soporte de WhatsApp. Envíame el código de 6 dígitos que te llegó por SMS.", ["WhatsApp"]),
    ("Estimado(a) {full}, su cuenta BCP ha sido bloqueada por seguridad. Ingrese al enlace para reactivarla.", ["BCP"]),
    ("¡Felicidades {first}! Ganaste S/ 5,000 en el sorteo de aniversario de Yape. Escríbele a la Lic. {full2} para cobrar.", ["Yape"]),
    ("Buenas tardes {first}, soy {full2} de Recursos Humanos de Falabella. Quedaste seleccionado, solo paga S/ 60 por el examen médico.", ["Falabella"]),
    ("Préstamo aprobado para {full} sin revisar Infocorp. Para el desembolso deposita S/ 150 a nombre de {full2}.", ["Infocorp"]),
    ("Vendo iPhone 15 nuevo a S/ 1,200, contactar a {first} {surname}. Solo pago adelantado por Plin.", ["Plin"]),
    ("{nick}, soy yo, tu primo. Estoy en problemas, no llames a mi mamá, solo yapéame.", []),
    ("hola {first_lower}, soy {first2_lower}, este es mi nuevo número, guárdalo.", []),
    ("Sr. {surname}, le saluda el Ing. {full2} de Interbank. Su tarjeta fue clonada, confírmenos los datos.", ["Interbank"]),
    ("Mi nombre es {full} y le escribo de la PNP. Su hijo {first2} está detenido.", ["PNP"]),
    ("Soy {full_plain}, agente de Scotiabank, verifique su clave dinamica en el enlace.", ["Scotiabank"]),
    ("Hola {first}, tu pedido llegó a la portería. Saludos.", []),
    ("Sra. {surname}, le recordamos su cita en EsSalud el lunes a las 9.", ["EsSalud"]),
    ("{first}, mañana es la reunión de padres a las 7, no te olvides.", []),
    ("Buen día, el Dr. {full} confirma su consulta para el jueves.", []),
    ("¡Feliz cumpleaños {nick}! Te queremos mucho.", []),
    ("{first} y {first2} ya llegaron a Arequipa, todo bien por acá.", []),
    ("Te escribe {full}, la profesora de tu hijo. Mañana no hay clases.", []),
]  # fmt: skip

# Messages without people: brands must survive and places must not be taken for names.
NEGATIVES: list[tuple[str, list[str]]] = [
    ("El BCP nunca te pedirá tu clave por WhatsApp.", ["BCP", "WhatsApp"]),
    ("Yape y Plin no envían premios por mensaje. Desconfía.", ["Yape", "Plin"]),
    ("Interbank te informa: tu estado de cuenta ya está disponible.", ["Interbank"]),
    ("Caja Huancayo y Mibanco tienen nuevas tasas para tu negocio.", ["Caja Huancayo", "Mibanco"]),
    ("La SUNAT y el RENIEC no piden pagos por WhatsApp.", ["SUNAT", "RENIEC", "WhatsApp"]),
    ("Banco de la Nación: tu pago de pensión está disponible.", ["Banco de la Nación"]),
    ("Llegué a San Juan de Lurigancho, ya estoy en el paradero.", []),
    ("Nos vemos en Villa María del Triunfo a las 5.", []),
    ("El paquete sale de Lima hacia Cusco mañana.", []),
]  # fmt: skip


def _plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


# Validation set: phrasings and names that the development set never uses.
VALIDATION_FIRST = [
    "Ximena", "Abel", "Débora", "Saúl", "Nelly", "Iván", "Emperatriz", "Washington", "Kevin",
    "Shirley", "Óscar", "Lourdes", "Fredy", "Gianella", "Américo", "Zoila", "Rubén", "Tatiana",
    "Edilberto", "Norma",
]  # fmt: skip
VALIDATION_SURNAMES = [
    "Inga", "Llanos", "Poma", "Ñaupari", "Tasayco", "Arroyo", "Mego", "Alarcón", "Huillca",
    "Coaquira", "Benites", "Chumpitaz", "Melgarejo", "Ayala", "Sullca",
]  # fmt: skip
VALIDATION_NICKNAMES = ["Chato", "Flaca", "Gordo", "Nena", "Chiquito", "Cholito"]
VALIDATION_TEMPLATES: list[tuple[str, list[str]]] = [
    ("Buenas noches, le habla {full} de la Caja Arequipa. Su crédito fue aprobado, falta un pago.", ["Caja Arequipa"]),
    ("Papá, es {first}. Se me malogró el celular, este es mi número temporal.", []),
    ("Querida {first}, gracias por tu compra. Tu pedido llegará pronto.", []),
    ("{full} te envió S/ 120 por Yape. Revisa tu app.", ["Yape"]),
    ("Señora {surname}, su hijo {first} tuvo un problema en el colegio, comuníquese con la directora {full2}.", []),
    ("Me llamo {full}, trabajo en la municipalidad y le escribo por una multa pendiente.", []),
    ("Hey {nick}! ¿Vienes al partido el domingo?", []),
    ("Ayúdame {first}, estoy varado en la carretera, mándame plata a nombre de {full2}.", []),
    ("Confirmamos la entrega para {full}, dirección registrada en Surco.", []),
    ("Atte. {full}, Jefe de Créditos, BanBif.", ["BanBif"]),
    ("{first} {surname} ha compartido un enlace contigo.", []),
    ("Gracias {first}, ya recibí el depósito.", []),
    ("Te saluda la Dra. {full2} del centro de salud, tu resultado está listo.", []),
    ("Mi amor, soy {first}, cambié de chip. Borra el número anterior.", []),
    ("Su asesor {full} lo atenderá en Mibanco el martes.", ["Mibanco"]),
    ("oye {first_lower}, ya llegué al paradero", []),
]  # fmt: skip
VALIDATION_NEGATIVES: list[tuple[str, list[str]]] = [
    ("Hola Mamá, ya llegué a la casa.", []),
    ("Buenos días, cliente. Su recibo de luz vence hoy.", []),
    ("Feliz Navidad a todos de parte de Interbank.", ["Interbank"]),
    ("Gracias Dios por este día.", []),
    ("Hola Lima, llega la feria gastronómica este fin de semana.", []),
    ("Estimado usuario, su cuenta Scotiabank fue actualizada.", ["Scotiabank"]),
    ("Mañana inicia la campaña de vacunación en Comas.", []),
]  # fmt: skip


def build(
    templates: list[tuple[str, list[str]]],
    negatives: list[tuple[str, list[str]]],
    *,
    first_names: list[str],
    surnames: list[str],
    nicknames: list[str],
    seed: int,
    variants: int,
    prefix: str,
) -> list[dict[str, object]]:
    rng = random.Random(seed)

    def full() -> str:
        return " ".join([rng.choice(first_names), *rng.sample(surnames, k=rng.choice([1, 2]))])

    records: list[dict[str, object]] = []
    for template, brands in templates:
        for _ in range(variants):
            first, first2 = rng.sample(first_names, k=2)
            slots = {
                "first": first,
                "first2": first2,
                "surname": rng.choice(surnames),
                "full": full(),
                "full2": full(),
                "nick": rng.choice(nicknames),
                "first_lower": first.lower(),
                "first2_lower": first2.lower(),
            }
            slots["full_plain"] = _plain(slots["full"])
            used = [key for key in slots if "{" + key + "}" in template]
            records.append(
                {
                    "text": template.format(**slots),
                    "names": [slots[key] for key in used],
                    "brands": brands,
                }
            )
    records += [{"text": text, "names": [], "brands": brands} for text, brands in negatives]
    return [{"id": f"{prefix}{index:03d}", **record} for index, record in enumerate(records, 1)]


def write(path: Path, records: list[dict[str, object]]) -> None:
    lines = [json.dumps(record, ensure_ascii=False) for record in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote {len(lines)} cases to {path}")


if __name__ == "__main__":
    write(
        OUTPUT,
        build(
            NAME_TEMPLATES,
            NEGATIVES,
            first_names=FIRST,
            surnames=SURNAMES,
            nicknames=NICKNAMES,
            seed=SEED,
            variants=VARIANTS,
            prefix="n",
        ),
    )
    write(
        VALIDATION_OUTPUT,
        build(
            VALIDATION_TEMPLATES,
            VALIDATION_NEGATIVES,
            first_names=VALIDATION_FIRST,
            surnames=VALIDATION_SURNAMES,
            nicknames=VALIDATION_NICKNAMES,
            seed=VALIDATION_SEED,
            variants=VALIDATION_VARIANTS,
            prefix="v",
        ),
    )
