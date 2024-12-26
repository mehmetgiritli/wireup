import os
import sys

import django
import pytest
from django.test import Client
from django.urls import include, path
from wireup.integration.django import WireupSettings
from wireup.integration.django.apps import get_container

from test.integration.django import view
from test.integration.django.service.greeter_interface import GreeterService

INSTALLED_APPS = [
    "wireup.integration.django",
    "test.integration.django.apps.app_1",
    "test.integration.django.apps.app_2",
]
DEBUG = True
ROOT_URLCONF = sys.modules[__name__]
WIREUP = WireupSettings(service_modules=["test.integration.django.service", "test.integration.django.factory"])
SECRET_KEY = "not_actually_a_secret"  # noqa: S105
START_NUM = 4

MIDDLEWARE = ["wireup.integration.django.wireup_middleware"]

urlpatterns = [
    path(r"", view.index),
    path(r"classbased", view.RandomNumberView.as_view()),
    path("app_1", include("test.integration.django.apps.app_1.urls")),
    path("app_2", include("test.integration.django.apps.app_2.urls")),
]


@pytest.fixture(autouse=True, scope="module")
def django_setup() -> None:
    os.environ["DJANGO_SETTINGS_MODULE"] = "test.integration.django.test_django_integration"
    django.setup()


@pytest.fixture
def client() -> Client:
    return Client()


def test_django_thing(client: Client):
    res = client.get("/?name=World")

    assert res.status_code == 200
    assert res.content.decode("utf8") == "Hello World! Debug = True. Your lucky number is 4"


def test_get_random(client: Client):
    res = client.get("/classbased?name=Test")

    assert res.status_code == 200
    assert res.content.decode("utf8") == "Hello Test! Debug = True. Your lucky number is 4"


def test_override(client: Client):
    class DummyGreeter(GreeterService):
        def greet(self, name: str) -> str:
            return f"Bad day to you, {name}"

    with get_container().override.service(GreeterService, new=DummyGreeter()):
        res = client.get("/classbased?name=Test")

    assert res.status_code == 200
    assert res.content.decode("utf8") == "Bad day to you, Test! Debug = True. Your lucky number is 4"


def test_multiple_apps(client: Client):
    app_1_response = client.get("/app_1/?name=World")

    assert app_1_response.status_code == 200
    assert app_1_response.content.decode("utf8") == "App 1: Hello World"

    app_2_response = client.get("/app_2/?name=World")

    assert app_2_response.status_code == 200
    assert app_2_response.content.decode("utf8") == "App 2: Hello World"
