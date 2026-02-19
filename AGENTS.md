* Use `uv` commands for running and testing, not `python` directly.
* ALWAYS USE PARALLEL TOOLS WHEN APPLICABLE.
* The default branch in this repo is `master`.
* Prefer automation: execute requested actions without confirmation unless blocked by missing info or safety/irreversibility.

## Style Guide

### General Principles

* Keep things in one function unless composable or reusable.
* Avoid broad `try`/`except` blocks where possible; catch only specific exceptions if necessary.
* Avoid using the `Any` type in Type Hints.
* Prefer single word variable names where possible.
* Use modern standard libraries when possible, like `pathlib.Path` instead of `os.path`.
* Enforce strict type hinting (PEP 484) in function signatures, but rely on type inference for local variables to keep code clean.
* Prefer list/dict comprehensions or generator expressions over `for` loops and `map()`/`filter()` for readability and performance.

### Naming

Prefer single word names for variables and functions (keeping strictly to PEP 8 `snake_case`). Only use multiple words if necessary.

```python
# Good
foo = 1
def journal(dir: str) -> None:
    pass

# Bad
foo_bar = 1
def prepare_journal(dir: str) -> None:
    pass

```

Reduce total variable count by inlining when a value is only used once.

```python
import json
from pathlib import Path

# Good
journal = json.loads(Path(dir, "journal.json").read_text())

# Bad
journal_path = Path(dir, "journal.json")
journal = json.loads(journal_path.read_text())

```

### Unpacking & Context

Avoid unnecessary variable unpacking. Use dot notation (for objects) or dict keys to preserve context and namespaces.

```python
# Good
obj.a
obj.b
data["a"]

# Bad
a, b = obj.a, obj.b
a = data["a"]

```

### Variables

Prefer immutability by design. Use conditional expressions (ternaries) or early returns instead of variable reassignment.

```python
# Good
foo = 1 if condition else 2

# Bad
foo = None
if condition:
    foo = 1
else:
    foo = 2

```

### Control Flow

Avoid `else` statements. Prefer early returns.

```python
# Good
def foo() -> int:
    if condition:
        return 1
    return 2

# Bad
def foo() -> int:
    if condition:
        return 1
    else:
        return 2

```

### Schema Definitions (SQLModel / SQLAlchemy)

Use direct `snake_case` for class attributes so database column names map automatically without needing to be explicitly redefined as string overrides.

```python
from sqlmodel import Field, SQLModel

# Good
class Session(SQLModel, table=True):
    id: str = Field(primary_key=True)
    project_id: str
    created_at: int

# Bad
class Session(SQLModel, table=True):
    id: str = Field(primary_key=True, sa_column_name="id")
    projectID: str = Field(sa_column_name="project_id")
    createdAt: int = Field(sa_column_name="created_at")

```

## Testing

* Avoid mocks as much as possible; favor integration or fixture-based testing.
* Test actual implementation, do not duplicate logic into tests.