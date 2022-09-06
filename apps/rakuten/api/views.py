from http import HTTPStatus

import requests
from rest_framework.response import Response
from rest_framework.views import APIView


class RakutenSearchViewAPI(APIView):
    permission_classes = []
    authentication_classes = []

    def get(self, request, *args, **kwargs):
        search_url = self.get_search_url(request, *args, **kwargs)
        rakuten_response = self.send_request_to_rakuten_api(search_url)
        handled_response = self.handle_response(rakuten_response)
        return Response(data=handled_response, status=HTTPStatus.OK)

    def get_search_url(self, request, *args, **kwargs):
        pass

    def send_request_to_rakuten_api(self, search_url):
        with requests.Session() as s:
            response = s.get(search_url)
            return response.json()

    def handle_response(self, rakuten_response):
        pass


rakuten_search_view_api = RakutenSearchViewAPI.as_view()
