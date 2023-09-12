# WireUp

Dependency injection library designed to provide a powerful and flexible way to manage and inject 
dependencies making it easier to develop, test, and maintain Python codebases.

Supports Python 3.8 and above.

---
## Quickstart guide

Demonstration of a simple application with two services (classes that provide functionality)
and parameters (app configuration) showing automatic dependency resolution and injection (autowiring) 
for services and a simple web view called "greet".

**1. Register dependencies**

```python
from wireup import container, Wire

# Parameters serve as configuration for services. 
# Think of a database url or environment name.
container.params.update({
    "db.connection_str": os.environ.get("DATABASE_URL") 
    "cache_dir": gettempdir(),
    "env": os.environ.get("ENV", "dev")
})


# Register a class as a dependency in the container.
# Constructor injection is supported for regular classes as well as dataclasses.
# In turn this can also depend on other objects in the container.
@container.register
class DbService:
    # Inject a parameter by name
    connection_str: Annotated[str, Wire(param="db.connection_str")],
    # Or by interpolating multiple parameters into a string
    cache_dir: Annotated[str, Wire(expr="${cache_dir}/${env}/db")],


@container.register
@dataclass
class UserRepository:
    db: DbService  # Services may also depend on other dependencies.
```

**2. Inject**

```python
@app.route("/greet/<str:name>")
@container.autowire
# Decorate all targets where the library must perform injection,such as views in a web app.
# Classes are automatically injected based on annotated type. 
# Parameters will be located based on the hint given in their default value.
def greet(name: str, user_repository: UserRepository, env: Annotated[str, Wire(param="env")]):  
    ...
```

**Installation**

```bash
# Install using poetry:
poetry add wireup

# Install using pip:
pip install wireup
```

## Documentation

For more information [check out the documentation](https://maldoinc.github.io/wireup/0.2.0)
