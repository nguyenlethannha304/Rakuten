from django.conf import settings
import re


class URLRakutenAdapter:
    PRICE_FILTER_STRING_PATTERN = r'\d+\.\.\d+'

    def __init__(self, request, **kwargs):
        self.request = request
        self.query_params = self._get_query_params()

    def merge_query_params_to_string(self, list_params_to_merge):
        """
        Chọn những query cần thiết cho endpoint
        (Bắt buộc phải có applicationId để xác thực)

        Argument list_params_to_merge = [str, str, str]
        """
        rv = []
        for param in list_params_to_merge:
            if (value := getattr(self, param, None)):
                rv.append(value)
        # Sử dụng version 2 của rakuten cho nhẹ hơn
        rv.append("formatVersion=2")
        return rv.join('&')

    @property
    def host(self):
        if hasattr(settings, 'RAKUTEN_ENV'):
            return settings.RAKUTEN_ENV
        return 'https://app.rakuten.co.jp/services/api/'

    @property
    def product_api(self):
        return 'Product/Search/20170426'
    # START QUERY PARAM

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
    def genreId(self):
        if self.query_params.get('', None):
            return f""

    @property
    def productId(self):
        product_id = self._get_product_id_from_url()
        if product_id:
            return f"productId={product_id}"

    def _get_product_id_from_url(self):
        last_path = self.request.path.split('/')[-1]
        product_path = last_path.split('.')[0]
        product_id = product_path.split('-')[-1]
        return product_id

    @property
    def hits(self):
        # Số lượng sản phẩm trả về
        if self.query_params.get('limit', None):
            return f"hits={self.query_params.get('')}"
        return "hits=10"

    @property
    def page(self):
        if self.query_params.get('page', None):
            return f"page={self.query_params.get('page')}"
        return "page=1"

    @property
    def min_max_list(self):
        # Min = min_max_list[0], Max = min_max_list[1]
        return self._get_min_max_from_filter_price()

    @property
    def minPrice(self):
        if self.min_max_list:
            return f"minPrice={self.min_max_list[0]}"

    @property
    def maxPrice(self):
        if self.min_max_list:
            return f"maxPrice={self.min_max_list[1]}"
    # END QUERY PARAM

    def _get_min_max_from_filter_price(self):
        filter_string = self.query_params('filter', None)
        if filter_string and (match := re.search(self.PRICE_FILTER_STRING_PATTERN, filter_string)):
            return match[0].split('..')

    def _get_query_params(self):
        """
        Query_params của request của rest_framework là query_params
        Query_params của request của django là GET
        """
        if hasattr(self.request, 'query_params'):
            return self.request.query_params
        if hasattr(self.request, 'GET'):
            return self.request.GET


class ProductRakutenAdapter:
    def __init__(self, **kwargs):
        pass
