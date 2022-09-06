from django.conf import settings
import re
PRICE_FILTER_STRING_PATTERN = r'\[(\d+)\.\.(\d+)\]'


class URLRakutenAdapter:
    def __init__(self, request, **kwargs):
        self.request = request
        self.min_max_tuple = self.get_price_filter_string()

    @property
    def keyword(self):
        if self.request.query_params.get('q', None):
            return f"keyword={self.request.query_params.get('q')}"

    @property
    def productId(self):
        if self.request.query_params.get('', None):
            pass

    @property
    def hits(self):
        return 'hits='

    @property
    def page(self):
        if self.request.query_params.get('page', None):
            return f"page={self.request.query_params.get('page')}"

    @property
    def minPrice(self):
        return 'minPrice='

    @property
    def maxPrice(self):
        return 'maxPrice='

    def get_min_max_from_filter_price(self):
        filter_string = self.request.query_params('filter', None)
        if filter_string:
            match = re.match(PRICE_FILTER_STRING_PATTERN, filter_string)


class ProductRakutenAdapter:
    def __init__(self, **kwargs):
        pass
