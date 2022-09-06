def get_fee(price, usa_ship_price, country_code, partner, **kwargs):
    """
    - Lấy mã quốc gia truyền vào đi tìm trông bảng WareHouse, nếu không có thì lấy default WareHouse
      Thuế sẽ lấy theo giá trị của WareHouse này.
    - Search từng param trong chuỗi json truyền vào với điều kiện là mã quốc gia và mã đối tác truyền vào.
      Nếu không tìm thấy, truyền param đó + mã đối tác vào hàm lấy giá trị mặc định xử lý.
    - Hàm lấy giá trị mặc định sẽ tìm param đó + mã quốc gia là rỗng + mã đối tác.
      Nếu không tìm thấy thì thử lại với param đó + value là rỗng + mã quốc gia là rỗng + mã đối tác.
      Nếu vẫn không tìm thấy thì trả về None để xét lỗi.
    - Nếu tìm thấy giá trị cần tìm thì kiểm tra kiểu giá phải tính là percent hay fixed để cộng lại cho phù hợp.
    """
    fixed = 0
    percent = 0
    try:
        warehouse = Warehouse.objects.get(country_code=country_code)
    except Warehouse.DoesNotExist:
        warehouse = Warehouse.objects.get(country_code='US', state='OR')
    except Warehouse.MultipleObjectsReturned:
        warehouse = Warehouse.objects.get(country_code='US', state='OR')
    # get tax
    tax_percent = warehouse.tax

    # Giá đã bao gồm phí vận chuyển Mỹ và thuế Mỹ
    base_price = price * (1 + (tax_percent / 100)) + usa_ship_price

    params = kwargs['params']
    for att_code, att_value in params.items():
        qs = AttributeValue.objects.filter(code=att_code, value=att_value, country_code=country_code, partner=partner)
        if att_code == 'price':
            qs = AttributeValue.objects.filter(code=att_code, country_code=country_code, partner=partner)
        if not qs.exists():
            fee_type, fee_value, minimum = get_default_fee_value(att_code, att_value, partner)
        else:
            fee_type, fee_value, minimum = qs[0].type, float(qs[0].fee), qs[0].minimum

        if fee_type is None and fee_value is None:
            return None, None

        if fee_type == 'PERCENT':
            if minimum is not None:
                if base_price * (fee_value / 100) >= minimum:
                    percent += fee_value
                else:
                    fixed += minimum
            else:
                percent += fee_value
        else:
            fixed += fee_value
    return tax_percent, fixed, percent
