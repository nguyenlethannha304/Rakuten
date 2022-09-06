from http import HTTPStatus

import requests
from django.views import View
from django.http import JsonResponse
from apps.rakuten.utils import URLRakutenAdapter
from django.conf import settings


class RakutenSearchViewAPI(View):
    # START GET METHOD
    def get(self, request, *args, **kwargs):
        enpoint = self.get_endpoint(request, *args, **kwargs)
        rakuten_response = self.send_request_to_rakuten_api(enpoint)
        if self.is_response_success(rakuten_response):
            handled_response = self.handle_response(rakuten_response)
            return JsonResponse(data=handled_response, status=HTTPStatus.OK)
        return JsonResponse(data=rakuten_response.body, status=rakuten_response.status_code)

    def get_endpoint(self, request, *args, **kwargs):
        url = URLRakutenAdapter(request)
        query_param_name_list = [
            'applicationId', 'keyword', 'hits', 'page', 'minPrice', 'maxPrice']
        return url.host + url.search_product_api + url.merge_query_params_to_string(query_param_name_list)

    def send_request_to_rakuten_api(self, enpoint):
        with requests.Session() as s:
            return s.get(enpoint)

    def is_response_success(self, response):
        if response.status_code:
            pass

    def handle_response(self, rakuten_response):
        pass
    # END GET METHOD


rakuten_search_view_api = RakutenSearchViewAPI.as_view()
