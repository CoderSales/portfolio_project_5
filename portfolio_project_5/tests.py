"""Smoke-test the storefront and storage configuration after framework upgrades."""

from decimal import Decimal
import subprocess
import sys
import textwrap
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.storage import StaticFilesStorage
from django.core.files.storage import FileSystemStorage, storages
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from products.models import Category, Product


class StorefrontSmokeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        category = Category.objects.create(name="jackets", friendly_name="Jackets")
        cls.product = Product.objects.create(
            category=category,
            name="Upgrade test jacket",
            description="A product used only by the test database.",
            price=Decimal("60.00"),
            image="test-product.jpg",
        )
        cls.owner = get_user_model().objects.create_superuser(
            username="store_owner", email="owner@example.invalid", password=None
        )

    def setUp(self):
        for operation in ("connect", "connect_ex"):
            blocker = patch(
                "socket.socket." + operation,
                side_effect=AssertionError("Storefront tests must not use the network"),
            )
            blocker.start()
            self.addCleanup(blocker.stop)
        session = self.client.session
        session["bag"] = {str(self.product.pk): 2}
        session.save()

    def test_public_pages_render_products_and_bag(self):
        pages = (
            (reverse("home"), "home/index.html"),
            (reverse("products"), "products/products.html"),
            (reverse("product_detail", args=[self.product.pk]),
             "products/product_detail.html"),
            (reverse("view_bag"), "bag/bag.html"),
        )
        for url, template in pages:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, template)
                self.assertEqual(response.context["product_count"], 2)
                self.assertEqual(response.context["grand_total"], Decimal("120.00"))
                if template != "home/index.html":
                    self.assertContains(response, self.product.name)

    def test_store_owner_product_forms_render_bootstrap_and_image_widget(self):
        self.client.force_login(self.owner)
        for url_name, args in (("add_product", []), ("edit_product", [self.product.pk])):
            with self.subTest(page=url_name):
                response = self.client.get(reverse(url_name, args=args))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'name="name"')
                self.assertContains(response, 'name="image"')
                self.assertContains(response, "form-control")
                self.assertContains(response, "Select Image")
                if url_name == "edit_product":
                    self.assertContains(response, "/media/test-product.jpg")

    def test_checkout_renders_country_and_payment_fields_without_calling_stripe(self):
        with patch(
            "checkout.views.stripe.PaymentIntent.create",
            return_value=SimpleNamespace(client_secret="pi_test_secret_test"),
        ) as create_intent:
            response = self.client.get(reverse("checkout"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "checkout/checkout.html")
        self.assertContains(response, 'name="full_name"')
        self.assertContains(response, 'name="country"')
        self.assertContains(response, 'value="IE"')
        self.assertContains(response, "pi_test_secret_test")
        create_intent.assert_called_once_with(amount=12000, currency="usd")


class StorageConfigurationTests(SimpleTestCase):
    def test_test_settings_use_local_file_backends(self):
        self.assertIsInstance(storages["default"], FileSystemStorage)
        self.assertIsInstance(storages["staticfiles"], StaticFilesStorage)
        self.assertEqual(storages["default"].url("photo.jpg"), "/media/photo.jpg")
        self.assertEqual(storages["staticfiles"].url("app.css"), "/static/app.css")

    def test_aws_settings_resolve_both_backends_without_network_or_database(self):
        # A fresh process exercises the real USE_AWS settings branch without
        # inheriting credentials, DATABASE_URL, or cached storage objects.
        program = textwrap.dedent("""
            from unittest.mock import patch

            blocked = AssertionError("Storage configuration must not perform I/O")
            with patch("socket.socket.connect", side_effect=blocked), \\
                 patch("socket.socket.connect_ex", side_effect=blocked), \\
                 patch("sqlite3.connect", side_effect=blocked):
                import django
                django.setup()
                from django.conf import settings
                from django.core.files.storage import storages
                from custom_storages import MediaStorage, StaticStorage

                media = storages["default"]
                static = storages["staticfiles"]
                assert isinstance(media, MediaStorage)
                assert isinstance(static, StaticStorage)
                assert media.location == "media"
                assert static.location == "static"
                assert media.url("photo.jpg") == settings.MEDIA_URL + "photo.jpg"
                assert static.url("app.css") == settings.STATIC_URL + "app.css"
        """)
        result = subprocess.run(
            [sys.executable, "-c", program],
            cwd=settings.BASE_DIR,
            env={
                "DJANGO_SETTINGS_MODULE": "portfolio_project_5.settings",
                "SECRET_KEY": "isolated-storage-configuration-test",
                "DEVELOPMENT": "1",
                "USE_AWS": "1",
                "AWS_ACCESS_KEY_ID": "test-only-key",
                "AWS_SECRET_ACCESS_KEY": "test-only-secret",
                "AWS_EC2_METADATA_DISABLED": "true",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
