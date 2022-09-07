from django.test import TestCase
from collections import namedtuple
from .utils import ProductRakutenAdapter, URLRakutenAdapter
# Create your tests here.

Request = namedtuple('Request', ('path', 'query_params'))


class TestURLRakutenAdapter(TestCase):
    def setUp(self):
