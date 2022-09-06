import json
import re
import time

import requests
import unidecode
import xmltodict
from django.conf import settings
from django.core.cache import cache

from ebay.hub import hub_product, refesh_auth_token
from ebay.utils import is_item_in_american
from product.models import Product
from xanhluc.tasks import debug
from translators.views import translator as t
from user_api.models import UserApi
from utils.cache_vars.get_shipping_data import (
    ITEM_SHIPPING_DATA_TIME_CACHE,
    ITEM_SHIPPING_DATA_CACHE_NAME
)
from utils.cache_vars.product_detail import (
    PRODUCT_DETAIL_CACHE_NAME,
    PRODUCT_DETAIL_CACHE_TIME
)


def conver_url(url_link):
    text = unidecode.unidecode(url_link).lower()
    return re.sub(r'[\W_]+', '-', text)


def request_ebay_api_get_shipping_data(item_id, quantity, is_bot_request, **kwargs):
    """
    - Hàm request qua eBay API để lấy thông tin ship
    - Dùng trong trường hợp API sản phẩm không trả về thông tin ship hoặc có nhưng itemLocation không phải US
    """

    def execute(_url, _data, _headers):
        response = requests.post(_url, data=_data, headers=_headers)
        parse = xmltodict.parse(response.text)
        dumps = json.dumps(parse)
        result = json.loads(dumps)
        return result

    country_code = kwargs.get('country_code')
    postal_code = kwargs.get('postal_code', '')
    # nếu có thông tin ship trong cache thì lấy và trả về luôn, ko cần request qua eBay
    shipping_data_cache_name = ITEM_SHIPPING_DATA_CACHE_NAME.format(
        item_id=item_id, country_code=country_code, postal_code=postal_code
    )
    try:
        shipping_data = cache.get(shipping_data_cache_name)
    except Exception:
        shipping_data = None

    if shipping_data is not None:
        return shipping_data

    app = UserApi.objects.get(default=True, is_app_for_bot=is_bot_request)

    item_legacy_id = item_id.split('|')[1]
    url = 'https://open.api.ebay.com/shopping'
    headers = {
        "X-EBAY-API-IAF-TOKEN": "Bearer " + app.token,
        "X-EBAY-API-SITE-ID": "0",
        "X-EBAY-API-CALL-NAME": "GetShippingCosts",
        "X-EBAY-API-VERSION": "863",
        "X-EBAY-API-REQUEST-ENCODING": "xml"
    }
    data = """
        <?xml version="1.0" encoding="utf-8"?>
        <GetShippingCostsRequest xmlns="urn:ebay:apis:eBLBaseComponents">
            <ItemID>""" + item_legacy_id + """</ItemID>
            <DestinationCountryCode>""" + country_code + """</DestinationCountryCode>
            <DestinationPostalCode>""" + postal_code + """</DestinationPostalCode>
            <IncludeDetails>true</IncludeDetails>
            <QuantitySold>""" + str(quantity) + """</QuantitySold>
        </GetShippingCostsRequest>
    """

    shipping_data = execute(url, data, headers)

    if 'GetShippingCostsResponse' in shipping_data \
            and 'Ack' in shipping_data['GetShippingCostsResponse'] \
            and shipping_data['GetShippingCostsResponse']['Ack'] == 'Failure' \
            and shipping_data['GetShippingCostsResponse']['Errors']['ShortMessage'] == 'Invalid token.':
        new_access_token = refesh_auth_token(app)
        if new_access_token is not None:
            app.token = new_access_token
            app.save()
            headers['X-EBAY-API-IAF-TOKEN'] = "Bearer " + app.token
            shipping_data = execute(url, data, headers)

    elif 'GetShippingCostsResponse' in shipping_data \
            and 'Ack' in shipping_data['GetShippingCostsResponse'] \
            and shipping_data['GetShippingCostsResponse']['Ack'] == 'Success':
        try:
            cache.set(shipping_data_cache_name, shipping_data, ITEM_SHIPPING_DATA_TIME_CACHE)
        except Exception:
            pass
    else:
        debug.delay(shipping_data, item_id=item_id, quantity=quantity, is_bot_request=is_bot_request)

    return shipping_data


def handle_from_ship_data_in_item_data(current_shipping_data):
    """
    - Hàm này dùng trong trường hợp ``data_item`` có trường ``shippingOptions`` và sẽ ship về kho default
    - Hàm sẽ xử lý lấy ra object ship có giá trị nhỏ nhất
    """
    us_ship_price = 0
    total_options = len(current_shipping_data)
    if total_options == 1 and 'shippingServiceCode' in current_shipping_data[0]:
        obj_ship_of_item = current_shipping_data[0]
    else:
        obj_ship_of_item = current_shipping_data[0]
        if 'shippingServiceCode' not in obj_ship_of_item:
            obj_ship_of_item['shippingServiceCode'] = 'unknown'
        if 'shippingCost' in obj_ship_of_item:
            us_ship_price = float(obj_ship_of_item['shippingCost']['value'])
        for obj in current_shipping_data:
            if 'shippingCost' in obj and 'shippingServiceCode' in obj:
                if obj['shippingServiceCode'] not in ['Local Pickup', 'Freight']:
                    if us_ship_price > float(obj['shippingCost']['value']):
                        us_ship_price = float(obj['shippingCost']['value'])
                        obj_ship_of_item = obj
    return obj_ship_of_item


# def handle_from_ship_data_after_get(data_item, item_quantity, is_bot_request, **kwargs):
def handle_from_ship_data_after_get(data_item, shipping_data_after_retrieving, **kwargs):
    """
    - Hàm này dùng trong trường hợp cần request qua eBay API để lấy thông tin ship
    - Hàm sẽ xử lý lấy ra object ship có giá trị nhỏ nhất
    """

    def internal_execute(data_item, min_ship_obj=None):
        # Hàm này chỉ được thực thi trong khuôn khổ hàm cha để tránh việc lặp lại code
        if 'estimatedAvailabilities' not in data_item:
            data_item['estimatedAvailabilities'] = [{
                'deliveryOptions': ['SELLER_ARRANGED_LOCAL_PICKUP']
            }]
        else:
            if 'deliveryOptions' not in data_item['estimatedAvailabilities'][0]:
                data_item['estimatedAvailabilities'][0]['deliveryOptions'] = ['SELLER_ARRANGED_LOCAL_PICKUP']
                if min_ship_obj is not None:
                    if 'ShippingServiceName' in min_ship_obj and \
                            min_ship_obj['ShippingServiceName'] not in ['Local Pickup', 'Freight']:
                        data_item['estimatedAvailabilities'][0]['deliveryOptions'] = ['SHIP_TO_HOME']
            else:
                if min_ship_obj is None and 'SELLER_ARRANGED_LOCAL_PICKUP' \
                        not in data_item['estimatedAvailabilities'][0]['deliveryOptions']:
                    data_item['estimatedAvailabilities'][0]['deliveryOptions'].append('SELLER_ARRANGED_LOCAL_PICKUP')

        _obj_ship_of_item = {}
        if min_ship_obj is not None:
            _obj_ship_of_item['shippingServiceCode'] = min_ship_obj['ShippingServiceName']
            _obj_ship_of_item['shippingCost'] = {}
            if 'ShippingServiceCost' in min_ship_obj:
                _obj_ship_of_item['shippingCost']['currency'] = min_ship_obj['ShippingServiceCost']['@currencyID']
                _obj_ship_of_item['shippingCost']['value'] = min_ship_obj['ShippingServiceCost']['#text']
            if 'EstimatedDeliveryMinTime' and 'EstimatedDeliveryMaxTime' in min_ship_obj:
                _obj_ship_of_item['minEstimatedDeliveryDate'] = min_ship_obj['EstimatedDeliveryMinTime']
                _obj_ship_of_item['maxEstimatedDeliveryDate'] = min_ship_obj['EstimatedDeliveryMaxTime']
        else:
            _obj_ship_of_item['shippingServiceCode'] = 'Local Pickup'
            _obj_ship_of_item['shippingCost'] = {}
            _obj_ship_of_item['shippingCost']['currency'] = 'USD'
            _obj_ship_of_item['shippingCost']['value'] = '0.00'

        if 'shippingOptions' in data_item:
            if _obj_ship_of_item not in data_item['shippingOptions']:
                data_item['shippingOptions'].append(_obj_ship_of_item)
        else:
            data_item['shippingOptions'] = [_obj_ship_of_item]
        return _obj_ship_of_item

    if shipping_data_after_retrieving['GetShippingCostsResponse']['Ack'] == 'Success':
        if 'ShippingDetails' in shipping_data_after_retrieving['GetShippingCostsResponse']:
            # option này thường là các ship nội địa (vd DE -> DE, JP -> JP)
            shipping_details = shipping_data_after_retrieving['GetShippingCostsResponse']['ShippingDetails']
            last_shipping_detail = shipping_data_after_retrieving['GetShippingCostsResponse']['ShippingCostSummary']
            if 'ShippingServiceOption' in shipping_details:
                shipping_options = shipping_details['ShippingServiceOption']
                if isinstance(shipping_options, dict):
                    minimum_shipping_obj = shipping_options
                    if 'ShippingServiceCost' in minimum_shipping_obj:
                        if minimum_shipping_obj['ShippingServiceCost']['@currencyID'] != 'USD':
                            minimum_shipping_obj['ShippingServiceCost']['@currencyID'] \
                                = last_shipping_detail['ShippingServiceCost']['@currencyID']
                            minimum_shipping_obj['ShippingServiceCost']['#text'] \
                                = last_shipping_detail['ShippingServiceCost']['#text']
                    if 'ShippingServiceName' in minimum_shipping_obj:
                        if minimum_shipping_obj['ShippingServiceName'] not in ['Local Pickup', 'Freight']:
                            obj_ship_of_item = internal_execute(data_item, minimum_shipping_obj)
                        else:
                            obj_ship_of_item = internal_execute(data_item)
                    else:
                        obj_ship_of_item = internal_execute(data_item)
                    return obj_ship_of_item
                elif isinstance(shipping_options, list):
                    # trường hợp các ship option eBay trả về là theo giá EUR
                    # nên cần kiểm tra xem có option nào trả về theo giá USD ko
                    # nếu có thì gán option đó là option mặc định, sau đó kiểm tra lại vs các option khác \
                    # xem có option nào tốt hơn không (chỉ kiểm tra với option cùng đơn vị tiền tệ)
                    flag = False
                    minimum_shipping_obj = None
                    for obj in shipping_options:
                        if 'ShippingServiceCost' in obj:
                            if '@currencyID' not in obj['ShippingServiceCost']:
                                continue
                            else:
                                if obj['ShippingServiceCost']['@currencyID'] == 'USD':
                                    if obj['ShippingServiceName'] not in ['Local Pickup', 'Freight']:
                                        flag = True
                                        minimum_shipping_obj = obj
                                        break
                    if flag:
                        us_ship_price = float(minimum_shipping_obj['ShippingServiceCost']['#text'])
                        for obj in shipping_options:
                            if obj['ShippingServiceName'] not in ['Local Pickup', 'Freight'] \
                                    and obj['ShippingServiceCost']['@currencyID'] == 'USD':
                                if us_ship_price > float(obj['ShippingServiceCost']['#text']):
                                    us_ship_price = float(obj['ShippingServiceCost']['#text'])
                                    minimum_shipping_obj = obj
                        obj_ship_of_item = internal_execute(data_item, minimum_shipping_obj)
                        return obj_ship_of_item
                    # trường hợp tất cả các ship option eBay trả về đều có đơn vị tiền tệ không là đơn vị USD
                    # thì ta sẽ lấy option `ShippingCostSummary`, option này sẽ có giá ship bằng USD được convert \
                    # từ đơn vị tiền tệ kia. Tuy nhiên, option này có thể sẽ không bao gồm ngày giao dự kiến.\
                    # Muốn lấy được cả ngày dự kiến nữa, phải kiểm tra ngược lại với các option trên, option nào \
                    # cùng giá sẽ lấy ngày dự kiến theo option đó.
                    else:
                        minimum_shipping_obj = last_shipping_detail
                        if 'EstimatedDeliveryMinTime' not in minimum_shipping_obj \
                                and 'EstimatedDeliveryMaxTime' not in minimum_shipping_obj:
                            if 'ListedShippingServiceCost' in minimum_shipping_obj:
                                for obj in shipping_options:
                                    if obj['ShippingServiceCost']['@currencyID'] \
                                            == minimum_shipping_obj['ListedShippingServiceCost']['@currencyID'] \
                                            and obj['ShippingServiceCost']['#text'] \
                                            == minimum_shipping_obj['ListedShippingServiceCost']['#text']:
                                        if 'EstimatedDeliveryMinTime' in obj:
                                            minimum_shipping_obj['EstimatedDeliveryMinTime'] \
                                                = obj['EstimatedDeliveryMinTime']
                                        if 'EstimatedDeliveryMaxTime' in obj:
                                            minimum_shipping_obj['EstimatedDeliveryMaxTime'] \
                                                = obj['EstimatedDeliveryMaxTime']
                                        break
                        obj_ship_of_item = internal_execute(data_item, minimum_shipping_obj)
                        return obj_ship_of_item
            # vì một số sản phẩm seller sẽ không ship nội địa nên sẽ cho về kho US
            # nên option này thường là các ship quốc tế (vd JP -> US, KR -> US)
            elif 'InternationalShippingServiceOption' in shipping_details:
                internal_ship_options = shipping_details['InternationalShippingServiceOption']
                if isinstance(internal_ship_options, dict):
                    minimum_shipping_obj = internal_ship_options
                    if 'ShippingServiceCost' in minimum_shipping_obj:
                        if minimum_shipping_obj['ShippingServiceCost']['@currencyID'] != 'USD':
                            minimum_shipping_obj['ShippingServiceCost']['@currencyID'] \
                                = last_shipping_detail['ShippingServiceCost']['@currencyID']
                            minimum_shipping_obj['ShippingServiceCost']['#text'] \
                                = last_shipping_detail['ShippingServiceCost']['#text']
                    if 'ShippingServiceName' in minimum_shipping_obj:
                        if minimum_shipping_obj['ShippingServiceName'] not in ['Local Pickup', 'Freight']:
                            obj_ship_of_item = internal_execute(data_item, minimum_shipping_obj)
                        else:
                            obj_ship_of_item = internal_execute(data_item)
                    else:
                        obj_ship_of_item = internal_execute(data_item)
                    return obj_ship_of_item
                elif isinstance(internal_ship_options, list):
                    flag = False
                    minimum_shipping_obj = None
                    for obj in internal_ship_options:
                        if 'ShippingServiceCost' in obj:
                            if '@currencyID' not in obj['ShippingServiceCost']:
                                continue
                            elif obj['ShippingServiceCost']['@currencyID'] == 'USD':
                                if obj['ShippingServiceName'] not in ['Local Pickup', 'Freight']:
                                    flag = True
                                    minimum_shipping_obj = obj
                                    break
                    if flag:
                        us_ship_price = float(minimum_shipping_obj['ShippingServiceCost']['#text'])
                        for obj in internal_ship_options:
                            if obj['ShippingServiceName'] not in ['Local Pickup', 'Freight']:
                                if us_ship_price > float(obj['ShippingServiceCost']['#text']):
                                    us_ship_price = float(obj['ShippingServiceCost']['#text'])
                                    minimum_shipping_obj = obj
                        obj_ship_of_item = internal_execute(data_item, minimum_shipping_obj)
                        return obj_ship_of_item
                    else:
                        minimum_shipping_obj = last_shipping_detail
                        if 'EstimatedDeliveryMinTime' not in minimum_shipping_obj \
                                and 'EstimatedDeliveryMaxTime' not in minimum_shipping_obj:
                            if 'ListedShippingServiceCost' in minimum_shipping_obj:
                                for obj in internal_ship_options:
                                    if obj['ShippingServiceCost']['@currencyID'] \
                                            == minimum_shipping_obj['ListedShippingServiceCost']['@currencyID'] \
                                            and obj['ShippingServiceCost']['#text'] \
                                            == minimum_shipping_obj['ListedShippingServiceCost']['#text']:
                                        if 'EstimatedDeliveryMinTime' in obj:
                                            minimum_shipping_obj['EstimatedDeliveryMinTime'] \
                                                = obj['EstimatedDeliveryMinTime']
                                        if 'EstimatedDeliveryMaxTime' in obj:
                                            minimum_shipping_obj['EstimatedDeliveryMaxTime'] \
                                                = obj['EstimatedDeliveryMaxTime']
                                        break
                        obj_ship_of_item = internal_execute(data_item, minimum_shipping_obj)
                        return obj_ship_of_item
            else:
                obj_ship_of_item = internal_execute(data_item)
                return obj_ship_of_item
        else:
            obj_ship_of_item = internal_execute(data_item)
            return obj_ship_of_item
    else:
        obj_ship_of_item = internal_execute(data_item)
        return obj_ship_of_item


def is_local_pickup_or_freight_item(obj_shipping):
    check = False
    if obj_shipping['shippingServiceCode'] == 'Local Pickup':
        check = True
    return check


def get_obj_ship_of_item(data_item, item_quantity, is_bot_request=False, **kwargs):
    country_code = kwargs.get('country_code')
    postal_code = kwargs.get('postal_code')
    if is_item_in_american(data_item) and 'shippingOptions' in data_item:
        obj_ship_of_item = handle_from_ship_data_in_item_data(data_item['shippingOptions'])
    else:
        shipping_data_after_retrieving = request_ebay_api_get_shipping_data(
            data_item['itemId'],
            item_quantity,
            is_bot_request,
            country_code=country_code,
            postal_code=postal_code
        )
        obj_ship_of_item = handle_from_ship_data_after_get(
            data_item, shipping_data_after_retrieving
        )
    return obj_ship_of_item


def get_the_smallest_usa_ship_price(obj_ship):
    try:
        try:
            usa_ship_price = float(obj_ship['shippingCost']['value'])
        except KeyError:
            try:
                usa_ship_price = float(obj_ship['ShippingServiceCost']['#text'])
            except KeyError:
                usa_ship_price = 0
        return usa_ship_price
    except TypeError:
        return 0


def get_the_smallest_usa_ship_price_for_each_additional_item(obj_ship):
    try:
        usa_ship_price_for_each_additional_item = float(obj_ship['additionalShippingCostPerUnit']['value'])
    except KeyError:
        try:
            usa_ship_price_for_each_additional_item = float(obj_ship['ShippingServiceAdditionalCost']['value'])
        except KeyError:
            usa_ship_price_for_each_additional_item = 0
    return usa_ship_price_for_each_additional_item


def translate_products_title(products):
    """
    Hàm này có nhiệm vụ dịch tiêu đề của từng object.
    Tham số đầu vào là 1 danh sách các object - là các sản phẩm của eBay.
    """
    products_translated = []
    for i in range(0, len(products), 50):
        items_list = products[i:i+50]
        title_dict = {}
        for index, item in enumerate(items_list):
            if '"' in item['title']:
                item['title'] = item['title'].replace('"', ' inch')
            title_dict[index] = item['title']
        paragraph = json.dumps(title_dict)
        try:
            vi_paragraph = t.translate(paragraph, dest='vi').__dict__()['text']
            vi_title_dict = {}
            try:
                vi_title_dict = json.loads(vi_paragraph)
            except json.decoder.JSONDecodeError:
                if '\\ ' in vi_paragraph:
                    vi_paragraph = vi_paragraph.replace('\\ ', '\\')
                if ' \\' in vi_paragraph:
                    vi_paragraph = vi_paragraph.replace(' \\', '\\')
                try:
                    vi_title_dict = json.loads(vi_paragraph)
                except json.decoder.JSONDecodeError:
                    pass
            try:
                for key, value in vi_title_dict.items():
                    if ' ' in key:
                        vi_title_dict[key.strip()] = vi_title_dict.pop(key)
            except RuntimeError:
                for key, value in vi_title_dict.items():
                    if ' ' in key:
                        vi_title_dict[key.strip()] = vi_title_dict.pop(key)
        except:
            vi_title_dict = json.loads(paragraph)

        for index, item in enumerate(items_list):
            try:
                item['title'] = vi_title_dict[str(index)]
            except KeyError:
                pass
            products_translated.append(item)
    return products_translated


def add_product_colum(objData, google_merchant_pk):
    # s=time.time()
    # items = translate_products_title(objData)
    items = objData
    # print('translate time ', time.time() - s)
    products = []
    # s = time.time()
    for item in items:
        # a.append(item['itemId'])
        title = item['title']

        # get image list of item
        if 'additionalImages' in item:
            image = item['additionalImages']
        else:
            if 'image' in item:
                image = [{"imageUrl": item['image']['imageUrl']}]
            else:
                image = [{"imageUrl": ""}]

        if 'price' in item:
            price = float(item['price']['value'])
        else:
            if 'currentBidPrice' in item:
                price = float(item['currentBidPrice']['value'])
            else:
                price = 0

        # get percent
        if 'marketingPrice' in item:
            if 'discountPercentage' in item['marketingPrice']:
                percent = item['marketingPrice']['discountPercentage']
            else:
                percent = 0
            if 'originalPrice' in item['marketingPrice']:
                price_sales = item['marketingPrice']['originalPrice']['value']
            else:
                price_sales = price * 100 / (100 - float(percent))
        else:
            percent = 0
            price_sales = price * 100 / (100 - float(percent))

        try:
            category_id = item['categoryId']
        except KeyError:
            try:
                category_id = item['categories'][0]['categoryId']
            except IndexError:
                category_id = 0

        products.append(Product(
            itemId=item['itemId'],
            title=title,
            image=json.dumps(image),
            price=price,
            type=0,
            percent=percent,
            price_sales=price_sales,
            external_id=category_id,
            data=json.dumps(item),
            description=item['shortDescription'] if 'shortDescription' in item else '',
            og_image=item['image']['imageUrl'] if 'image' in item else '',
            create_date=time.time(),
            google_merchant=google_merchant_pk
        ))
    # print('handle data time ', time.time() - s)
    # s=time.time()
    Product.objects.bulk_create(products, ignore_conflicts=True)
    # print('save data time ', time.time() - s)
    # print("Lưu sản phẩm xuống database xong")


def add_product_all(objData, category_id):
    for json_parse_item in objData:
        # translate title
        try:
            vi_title = t.translate(json_parse_item['title'], dest='vi').__dict__()['text']
        except AttributeError:
            vi_title = json_parse_item['title']
        # get image list of item
        if 'additionalImages' in json_parse_item:
            image = json_parse_item['additionalImages']
        else:
            image = [{"imageUrl": json_parse_item['image']['imageUrl']}]

        if 'price' in json_parse_item:
            price = float(json_parse_item['price']['value'])
        else:
            if 'currentBidPrice' in json_parse_item:
                price = float(json_parse_item['currentBidPrice']['value'])
            else:
                price = 0
        # get percent
        if 'marketingPrice' in json_parse_item:
            if 'discountPercentage' in json_parse_item['marketingPrice']:
                percent = json_parse_item['marketingPrice']['discountPercentage']
            else:
                percent = 0
            if 'originalPrice' in json_parse_item['marketingPrice']:
                price_sales = json_parse_item['marketingPrice']['originalPrice']['value']
            else:
                price_sales = price * 100 / (100 - float(percent))
        else:
            percent = 0
            price_sales = price * 100 / (100 - float(percent))

        try:
            check_item_exist = Product.objects.get(itemId=json_parse_item['itemId'])
            check_item_exist.price = price
            check_item_exist.create_date = time.time()
            check_item_exist.external_id = category_id
            check_item_exist.data = json.dumps(json_parse_item)
            check_item_exist.save()
        except Product.DoesNotExist:
            obj_product = Product.objects.create(
                itemId=json_parse_item['itemId'],
                title=json_parse_item['title'],
                image=json.dumps(image),
                price=price,
                type=0,
                percent=percent,
                price_sales=price_sales,
                external_id=category_id,
                data=json.dumps(json_parse_item),
                description=json_parse_item['shortDescription'] if 'shortDescription' in json_parse_item else '',
                og_image=json_parse_item['image']['imageUrl'],
                create_date=time.time()
            )
            obj_product.save()
    print("addAll")


def get_detail(item_id, **kwargs):
    request = kwargs.get('request')
    product_detail_cache_name = PRODUCT_DETAIL_CACHE_NAME.format(item_id=item_id)
    data = cache.get(product_detail_cache_name)
    if not data:
        resp = hub_product(f'{settings.EBAY_ENVIRON}/buy/browse/v1/item/{item_id}', request=request)
        data = json.loads(resp.content)
        # nếu không phải là sản phẩm đấu giá thì lưu cache
        if 'buyingOptions' in data:
            if 'AUCTION' not in data['buyingOptions']:
                cache.set(product_detail_cache_name, data, PRODUCT_DETAIL_CACHE_TIME)
    return data


def get_detail_not_from_cache(item_id, **kwargs):
    request = kwargs.get('request')
    resp = hub_product(f'{settings.EBAY_ENVIRON}/buy/browse/v1/item/{item_id}', request=request)
    data = json.loads(resp.content)
    # nếu không phải là sản phẩm đấu giá thì lưu cache
    if 'buyingOptions' in data:
        if 'AUCTION' not in data['buyingOptions']:
            product_detail_cache_name = PRODUCT_DETAIL_CACHE_NAME.format(item_id=item_id)
            cache.set(product_detail_cache_name, data, PRODUCT_DETAIL_CACHE_TIME)
    return data
