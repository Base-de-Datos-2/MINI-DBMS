"""Stage 9 helpers shared by the API test modules."""

from api.database import Database
from api.demo import DEMO_MEMORY_BUDGET_BYTES, demo_database
from api.engine_service import EngineService


#: Smaller than the presentation fixture so the suite stays fast, yet still
#: large enough that sorting, grouping and joining spill under the demo budget.
BIG_STUDENTS = 60
BIG_ENROLLMENTS = 180


def small_demo():
    return demo_database(
        big_students_count=BIG_STUDENTS, big_enrollments_count=BIG_ENROLLMENTS
    )


def open_service(directory, *, allow_writes=False):
    database = Database.open(
        small_demo(), directory, memory_budget_bytes=DEMO_MEMORY_BUDGET_BYTES
    )
    return EngineService(database, allow_writes=allow_writes)


def query(client, sql, **options):
    return client.post("/api/query", json={"sql": sql, **options})


def names(node):
    """Operator names of a serialized plan node, parents before children."""

    return [node["name"]] + [
        name for child in node["children"] for name in names(child)
    ]


def details_of(node, name):
    """Details of the first operator called ``name`` in a serialized tree."""

    if node["name"] == name:
        return {pair["key"]: pair["value"] for pair in node["details"]}
    for child in node["children"]:
        found = details_of(child, name)
        if found is not None:
            return found
    return None
