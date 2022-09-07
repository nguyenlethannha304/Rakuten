from http import HTTPStatus

import requests
from rest_framework.exceptions import ValidationError
from rest_framework.views import APIView
from rest_framework.response import Response
from apps.rakuten.utils import URLRakutenAdapter


def send_request_to_rakuten_api(enpoint):
    with requests.Session() as s:
        return s.get(enpoint)


def is_response_success(response):
    if 200 <= response.status_code < 300:
        return True


class RakutenSearchAPIView(APIView):
    # START GET METHOD
    def get(self, request, *args, **kwargs):
        enpoint = self.get_endpoint(request, *args, **kwargs)
        rakuten_response = send_request_to_rakuten_api(enpoint)
        if is_response_success(rakuten_response):
            handled_response = self.handle_response(rakuten_response)
            return Response(data=handled_response, status=HTTPStatus.OK)
        # Return error response

    def get_endpoint(self, request, *args, **kwargs):
        url = URLRakutenAdapter(request)
        if self._is_endpoint_valid(url):
            query_param_name_list = [
                'applicationId', 'keyword', 'hits', 'page', 'minPrice', 'maxPrice']
            return url.host + url.product_api + "?" + url.merge_query_params_to_string(query_param_name_list)
        raise ValidationError('Query params không đúng. Yêu cầu có q=...')

    def handle_response(self, rakuten_response):
        pass

    def _is_endpoint_valid(self, url):
        if url.applicationId and url.keyword:
            return True
    # END GET METHOD


rakuten_search_api_view = RakutenSearchAPIView.as_view()


class RakutenDetailAPIView(APIView):
    # START GET METHOD
    def get(self, request, *args, **kwargs):
        endpoint = self.get_endpoint(request, *args, **kwargs)
        rakuten_response = send_request_to_rakuten_api(endpoint)
        if is_response_success(rakuten_response):
            handled_response = self.handle_response(rakuten_response)
            return Response(data=handled_response, status=HTTPStatus.OK)
        # Return error response

    def get_endpoint(self, request, *args, **kwargs):
        url = URLRakutenAdapter(request)
        if self._is_endpoint_valid(url):
            query_param_name_list = [
                "applicationId", "productId"
            ]
            return url.host + url.product_api + "?" + url.merge_query_params_to_string(query_param_name_list)

    def _is_endpoint_valid(url):
        if url.productId:
            return True
    # END GET METHOD
