import requests

from django.conf import settings

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from ebay.utils import (
    handle_data,
    handle_categories_distributions,
    handle_aspects_distributions,
    ebay_search_result
)
from external.models import External
from key_product.models import KeyProduct
from product.throttle import SearchAPIRateThrottle
from product.utils import handle_params_local_product_search
from utils.functional import is_google_bot


@api_view(['GET'])
@permission_classes([AllowAny, ])
@throttle_classes([SearchAPIRateThrottle])
def search_api(request):
    try:
        if 'type' in request.query_params and request.query_params['type'] == 'local':
            response = handle_params_local_product_search(request.query_params)
        else:
            # Ebay yêu cầu bắt buộc phải có ít nhất 1 trong các param: q, category_ids, charity_ids, epid, gtin
            # Nếu không có sẽ trả về lỗi
            if 'q' not in request.query_params:
                if 'category_ids' not in request.query_params:
                    if 'charity_ids' not in request.query_params:
                        if 'epid' not in request.query_params:
                            if 'gtin' not in request.query_params:
                                errors = {
                                    "errors": [
                                        {
                                            "errorId": 12001,
                                            "domain": "API_BROWSE",
                                            "category": "REQUEST",
                                            "message": "The call must have a valid 'q', 'category_ids', 'charity_ids', "
                                                       "'epid' or 'gtin' query parameter."
                                        }
                                    ]
                                }
                                return Response(errors, status=status.HTTP_400_BAD_REQUEST)
            else:
                # nếu có param `clientId` sẽ kiểm tra từ khóa tìm từ client đó có chưa,
                # nếu chưa sẽ lưu lại client + từ khóa đó
                if 'HTTP_CLIENTID' in request.META and request.query_params['q'] != '':
                    try:
                        key_search = KeyProduct.objects.get(
                            name__exact=request.query_params['q'].lower(
                            ).strip(),
                            client_id=request.META['HTTP_CLIENTID']
                        )
                        if key_search.hidden:
                            key_search.hidden = False
                            key_search.save()
                    except KeyProduct.DoesNotExist:
                        try:
                            key_search = KeyProduct.objects.create(
                                client_id=request.META['HTTP_CLIENTID'],
                                name=request.query_params['q'].lower().strip(),
                                limit=1
                            )
                            key_search.save()
                        except Exception:
                            pass

            response = ebay_search_result(request.query_params)
        if 'errors' in response:
            if response['errors'][0]['errorId'] == 2001:
                if is_google_bot(request):
                    r = requests.get(
                        f'{settings.API_DOMAIN}/api/send_mail/ebay-app-for-bot-error')
                    return Response(status=status.HTTP_406_NOT_ACCEPTABLE)
                else:
                    r = requests.get(
                        f'{settings.API_DOMAIN}/api/send_mail/ebay-app-for-user-error')
                    return Response(status=status.HTTP_400_BAD_REQUEST)
        data = {}
        data['keyword_from'] = response.get('keyword_from')
        data['trans_from_lang'] = response.get('trans_from_lang')
        data['keyword_to'] = response.get('keyword_to')
        data['total'] = response['total'] if 'total' in response else 0
        if 'itemSummaries' not in response:
            data['items'] = []
            data['refinement'] = {}
            category = ''
            if 'category_ids' in request.query_params:
                category = request.query_params['category_ids']
            data['refinement']['dominantCategoryId'] = category
            data['refinement']['categoryDistributions'] = []
            data['refinement']['aspectDistributions'] = []
            return Response(data, status=status.HTTP_200_OK)

        data['items'] = handle_data(response)
        categories = handle_categories_distributions(
            response, request.query_params)
        aspects = handle_aspects_distributions(response)

        if 'refinement' in response:
            data['refinement'] = {}
            if 'dominantCategoryId' in response['refinement']:
                data['refinement']['currentCategoryId'] = response['refinement']['dominantCategoryId']
            data['refinement'].update({'categoryDistributions': categories})
            data['refinement'].update({'aspectDistributions': aspects})
        else:
            data['refinement'] = {}
            data['refinement']['categoryDistributions'] = categories
            data['refinement']['aspectDistributions'] = aspects

        if 'q' not in request.query_params and 'category_ids' in request.query_params:
            try:
                cat = External.objects.get(
                    category=request.query_params['category_ids'])
                data['category_name'] = cat.name
            except External.DoesNotExist:
                pass

        if 'errors' in response:
            return Response(response, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response(data, status=status.HTTP_200_OK)
    except:
        data = {
            "keyword_from": None,
            "keyword_to": None,
            "total": 0,
            "items": [],
            "refinement": {
                "dominantCategoryId": "",
                "categoryDistributions": [],
                "aspectDistributions": []
            }
        }
        return Response(data, status=status.HTTP_200_OK)


def ebay_search_result(xabay_params, **kwargs):
    request = kwargs.get('request')
    # check condition: q
    # q là một chuỗi bao gồm một hoặc nhiều từ khóa được sử dụng để tìm kiếm các mục trên eBay.
    # Các từ khóa được xử lý như sau:
    # Nếu các từ khóa được phân tách bằng dấu phẩy (`,`) thì nó được coi là VÀ.
    # VD: search/?q=iphone,ipad => truy vấn này sẽ trả về các mục có iphone VÀ ipad
    # Nếu các từ khóa được phân tách bằng khoảng trắng (` `) thì nó được coi là HOẶC.
    # VD: search/?q=iphone ipad => truy vấn này sẽ trả về các mục có iphone HOẶC ipad

    q = ''
    keyword_from = keyword_to = trans_from_lang = None
    if 'q' in xabay_params and xabay_params['q']:
        keyword_from = xabay_params['q']
        query_search = urllib.parse.unquote(xabay_params['q'])
        regex_str = re.search(ebay_item_id_pattern, query_search)
        if regex_str is not None:
            ebay_item_id = query_search[regex_str.span()[0]:regex_str.span()[
                1]]
            check_list = ebay_item_id.split('i')
            if check_list[2] == '0':
                res = search_by_ebay_item_id(check_list[1])
            else:
                res = search_by_ebay_item_group_id(check_list[1])
            return res
        elif re.search('^(https://)', query_search) is not None:
            res = search_by_ebay_link(xabay_params['q'])
            return res
        else:
            if 'lang' in xabay_params and xabay_params['lang']:
                src = xabay_params['lang']
                key_translated, from_lang = translate_search_keyword(
                    xabay_params['q'], src=src)
            else:
                key_translated, from_lang = translate_search_keyword(
                    xabay_params['q'], src='auto')

            keyword_to = key_translated
            trans_from_lang = from_lang

            if 'trans' in xabay_params and xabay_params['trans'] == 'false':
                q = 'q=' + xabay_params['q']
            else:
                q = 'q=' + keyword_to
    # check condition: gtin
    # Trường này cho phép bạn tìm kiếm theo Số thương phẩm toàn cầu của mặt hàng được xác định bởi
    # https://www.gtin.info. Bạn chỉ có thể tìm kiếm theo UPC (Mã sản phẩm chung).
    # Nếu bạn có các định dạng khác của GTIN, bạn cần tìm kiếm theo từ khóa.
    # VD: search/?gtin=099482432621
    gtin = ''
    if 'gtin' in xabay_params:
        gtin = '&gtin=' + xabay_params['gtin']

    # check condition: charity_ids
    # charity_ids được sử dụng để giới hạn kết quả chỉ các mục được liên kết với tổ chức từ thiện được chỉ định.
    # Trường này có thể có một ID hoặc một danh sách ID được phân tách bằng dấu phẩy.
    # Phương thức sẽ trả về tất cả các mục liên quan đến các tổ chức từ thiện được chỉ định.
    # VD: search/?charity_ids=13-1788491,300108469
    charity_ids = ''
    if 'charity_ids' in xabay_params:
        charity_ids = '&charity_ids=' + xabay_params['charity_ids']

    # check condition: fieldgroups
    # Trường này là danh sách các giá trị được phân tách bằng dấu phẩy cho phép bạn kiểm soát những gì được trả về.
    # Mặc định là MATCHING_ITEMS, trả về các mục phù hợp với từ khóa hoặc danh mục được chỉ định.
    # Các giá trị khác bao gồm: ASPECT_REFINEMENTS, BUYING_OPTION_REFINEMENTS, CATEGORY_REFINEMENTS,
    # CONDITION_REFINEMENTS, EXTENDED, FULL
    fieldgroups = '&fieldgroups=MATCHING_ITEMS,CATEGORY_REFINEMENTS,ASPECT_REFINEMENTS'
    if 'fieldgroups' in xabay_params:
        fieldgroups = '&fieldgroups=' + xabay_params['fieldgroups']

    # check condition: compatibility_filter
    # Trường này chỉ định các thuộc tính được sử dụng để xác định một sản phẩm cụ thể.
    # Kết quả trả về là các mục khớp với từ khóa hoặc khớp với giá trị thuộc tính sản phẩm trong tiêu đề của mục.
    compatibility_filter = ''
    if 'compatibility_filter' in xabay_params:
        compatibility_filter = '&compatibility_filter=' + \
            xabay_params['compatibility_filter']

    # check condition: auto_correct
    # Một tham số truy vấn cho phép tự động sửa từ khóa tìm kiếm nếu nhập sai chính tả.
    # VD: search?q=macbok&auto_correct=KEYWORD
    auto_correct = ''
    if 'auto_correct' in xabay_params and xabay_params['auto_correct']:
        auto_correct = '&auto_correct=KEYWORD'

    # check condition: category_ids
    # ID danh mục được sử dụng để giới hạn kết quả.
    # Trường này có thể có một ID hoặc một danh sách ID được phân tách bằng dấu phẩy.
    category_ids = ''
    if 'category_ids' in xabay_params:
        category_ids = '&category_ids=' + xabay_params['category_ids']

    # check condition: filter
    # Trường này hỗ trợ các bộ lọc trường dữ liệu, có thể được sử dụng để giới hạn / tùy chỉnh tập kết quả.
    # VD: search?q=shirt&filter=price:[10..50],priceCurrency:USD
    # mặc định sẽ lọc theo tình trạng mua: mua ngay, đấu giá và trả giá
    filter = '&filter=buyingOptions:{FIXED_PRICE|AUCTION|BEST_OFFER},'
    if 'filter' in xabay_params:

        # Nếu có lọc theo buyingOtions thì bỏ giá trị mặc định và lấy giá trị hiện tại
        if 'bO' in xabay_params['filter']:
            filter = '&filter='

        # Tách từng điều kiện theo dấu ',' để check từ khóa truyền lên là gì
        # VD: &filter=p:[10..20],pC:USD => filter_conditions = ['p:[10..20]', 'pC:USD']
        filter_conditions = xabay_params['filter'].split(',')

        # đối với mỗi phần tử trong list filter_conditions tách nó thành 1 list 2 phần tu để so sánh tiếp
        # vd: 'p:[10..20]' => ['p', '[10..20]'], 'pC:USD' => ['pC', 'USD']
        for obj_filter in filter_conditions:
            keys = obj_filter.split(':')

            # lay gia tri day du. VD: p ~ price, pC ~ priceCurrency, bO ~ buyingOptions,...
            key = get_key_filter(keys[0])
            if key == 'sellers':
                filter += key + ':' + keys[1] + ','
            elif key == 'conditionIds':
                filter += key + ':' + keys[1] + ','

            # Nếu điều kiện là một object từ viết tắt thì sẽ lấy từng phần tử trong đó đi so sánh
            # với danh sách từ viết tắt. Nếu map thì lấy giá trị của từ viết tắt đó, không thì không lấy

            # check điều kiện lọc là 1 list
            # Nếu điều kiện là một list thì giữ nguyên
            if keys[1][0] == '[' and keys[1][-1] == ']':
                value_param = key + ':' + keys[1] + ','
            # check điều kiện lọc là 1 obj
            elif keys[1][0] == '{' and keys[1][-1] == '}':

                # tạo một mảng rỗng để khi lấy được giá trị của từ viết tắt sẽ đẩy vào mảng này
                arr = []
                value_list = keys[1][1:-1].split('|')
                if key in value_of_filter_condition_attribute.keys():
                    for value in value_list:
                        for k, v in value_of_filter_condition_attribute[key].items():
                            if value == k:
                                arr.append(v)
                # nếu mảng giá trị trên không có, sẽ lấy giá trị buyingOptions mặc định là tất cả
                # ngược lại sẽ lấy theo các giá trị trong mảng
                if not arr:
                    if keys[0] == 'bO':
                        value_param = 'buyingOptions:{FIXED_PRICE|AUCTION|BEST_OFFER},'
                    else:
                        value_param = ''
                elif len(arr) == 1:
                    value_param = key + ':{' + arr[0] + '},'
                elif len(arr) == 2:
                    value_param = key + ':{' + arr[0] + '|' + arr[1] + '},'
                else:
                    value_param = key + \
                        ':{' + arr[0] + '|' + arr[1] + '|' + arr[2] + '},'

            # Check điều kiện lọc là 1 chuỗi
            # Nếu đúng thì xem chuỗi đó có trong danh sách từ viết tắt ko
            # Nếu không có trong danh sách viết tắt thì giữ nguyên chuỗi
            # Ngược lại sẽ lấy giá trị của từ viết tắt đó
            else:
                if key not in value_of_filter_condition_attribute.keys():
                    pass
                else:
                    for k, v in value_of_filter_condition_attribute[key].items():
                        if k == keys[1]:
                            keys[1] = v
                value_param = key + ':' + keys[1] + ','

            filter += value_param
    # print(filter)

    # check condition: sort
    # Chỉ định thứ tự và tên trường sẽ sử dụng để sắp xếp các mục.
    # sort=price    Sắp xếp theo giá theo thứ tự tăng dần (giá thấp nhất trước)
    # sort=-price	Sắp xếp theo giá theo thứ tự giảm dần (giá cao nhất trước)
    # sort=distance	Sắp xếp theo khoảng cách theo thứ tự tăng dần (khoảng cách ngắn nhất trước)
    # sort=newlyListed	Sắp xếp theo ngày niêm yết (được liệt kê gần đây nhất / mục mới nhất trước)
    sort = ''
    sort_condition = ['price', '-price', 'distance', 'newlyListed']
    if 'sort' in xabay_params and xabay_params['sort'] in sort_condition:
        sort = '&sort=' + xabay_params['sort']

    # check condition: limit
    # Số lượng các mục, từ tập kết quả, được trả về trong một trang.
    # Mặc định: 52 (eBay là 50)
    # Số mục tối thiểu trên mỗi trang (giới hạn): 1
    # Số mục tối đa trên mỗi trang (giới hạn): 200
    limit = '&limit=52'
    if 'limit' in xabay_params:
        try:
            int_limit = int(xabay_params['limit'])
            if 1 <= int_limit <= 200:
                limit = '&limit=' + str(int_limit)
        except:
            limit = '&limit=52'

    # check condition: offset
    offset = '&offset=0'
    if 'page' in xabay_params:
        try:
            int_page = int(xabay_params['page'])
            if int_page > 0:
                offset = '&offset=' + \
                    str((int_page - 1) * int(limit.split('=')[1]))
        except:
            offset = '&offset=0'

    # check condition: aspect_filter
    # Trường này cho phép bạn lọc theo các khía cạnh mục.
    # Các cặp tên và giá trị khía cạnh, được yêu cầu sử dụng để giới hạn kết quả ở các khía cạnh cụ thể của mặt hàng.
    # VD: search?q=shirt&category_ids=15724&aspect_filter=categoryId:15724,Color:{Red}
    aspect_filter = ''
    if 'aspect_filter' in xabay_params:
        aspect_filter = '&aspect_filter=' + \
            urllib.parse.quote(xabay_params['aspect_filter'])

    # check condition: epid
    # EPID là định danh sản phẩm eBay của một sản phẩm từ danh mục sản phẩm eBay.
    # Trường này giới hạn kết quả chỉ các mục trong ePID được chỉ định.
    epid = ''
    if 'epid' in xabay_params:
        epid = '&epid=' + xabay_params['epid']

    ebay_search_endpoint = settings.EBAY_ENVIRON + '/buy/browse/v1/item_summary/search?' + q + gtin \
        + charity_ids + fieldgroups + compatibility_filter \
        + auto_correct + category_ids + filter + sort \
        + limit + offset + aspect_filter + epid
    # print(ebay_search_endpoint)
    products = hub_product(ebay_search_endpoint, request=request)
    products_parse = json.loads(products.content)

    if 'errors' not in products_parse:
        if 'itemSummaries' not in products_parse and 'q' in xabay_params:
            ebay_search_endpoint = settings.EBAY_ENVIRON + '/buy/browse/v1/item_summary/search?q=' + xabay_params['q'] \
                + gtin + charity_ids + fieldgroups + compatibility_filter \
                + auto_correct + category_ids + filter + sort \
                + limit + offset + aspect_filter + epid
            products = hub_product(ebay_search_endpoint, request=request)
            products_parse = json.loads(products.content)
    # else:
    #     print(products_parse)

    products_parse['keyword_from'] = keyword_from
    products_parse['keyword_to'] = keyword_to
    products_parse['trans_from_lang'] = trans_from_lang

    return products_parse
