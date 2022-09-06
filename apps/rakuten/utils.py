from django.conf import settings
import re


class URLRakutenAdapter:
    PRICE_FILTER_STRING_PATTERN = r'\d+\.\.\d+'

    def __init__(self, request, **kwargs):
        self.request = request
        self.query_params = self.get_query_params()
        # Min = min_max_list[0], Max = min_max_list[1]
        self.min_max_list = self.get_min_max_from_filter_price()

    def merge_query_params_to_string(self, list_params_to_merge):
        rv = []
        for param in list_params_to_merge:
            if (value := getattr(self, param, None)):
                rv.append(value)
        return '?' + rv.join('&')

    @property
    def host(self):
        if hasattr(settings, 'RAKUTEN_ENV'):
            return settings.RAKUTEN_ENV
        return 'https://app.rakuten.co.jp/services/api/'

    @property
    def search_product_api(self):
        return 'Product/Search/20170426'

    @property
    def applicationId(self):
        if hasattr(settings, 'RAKUTEN_ID'):
            return settings.RAKUTEN_ID
        return 'applicationId=1014989523353184170'

    @property
    def keyword(self):
        # Từ khóa tìm kiếm
        if self.query_params.get('q', None):
            return f"keyword={self.query_params.get('q')}"

    @property
    def productId(self):
        if self.query_params.get('', None):
            pass

    @property
    def hits(self):
        # Số lượng sản phẩm trả về
        if self.query_params.get('', None):
            return f"hits={self.query_params.get('')}"
        return "hits=10"

    @property
    def page(self):
        if self.query_params.get('page', None):
            return f"page={self.query_params.get('page')}"
        return "page=1"

    @property
    def minPrice(self):
        if self.min_max_list:
            return f"minPrice={self.min_max_list[0]}"

    @property
    def maxPrice(self):
        if self.min_max_list:
            return f"maxPrice={self.min_max_list[1]}"

    def get_min_max_from_filter_price(self):
        filter_string = self.query_params('filter', None)
        if filter_string and (match := re.search(self.PRICE_FILTER_STRING_PATTERN, filter_string)):
            return match[0].split('..')

    def get_query_params(self):
        if hasattr(self.request, 'query_params'):
            return self.request.query_params
        if hasattr(self.request, 'GET'):
            return self.request.GET


class ProductRakutenAdapter:
    def __init__(self, **kwargs):
        pass
