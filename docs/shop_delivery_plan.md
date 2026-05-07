# Shop Delivery Integration Plan

## Current Store Layer

- Mini app collects cart items, customer phone, city, address, delivery method, and comment.
- Bot stores orders in `shop_orders` and `shop_order_items`.
- Delivery status starts as `pending`; manual support can process the order now.

## Future DPD / Yandex Flow

1. Add credentials to `.env`.
2. Implement provider adapters with the interface in `bot/services/delivery_service.py`.
3. Add quote endpoint for the mini app:
   - input: city, address, cart weight/dimensions
   - output: provider, price, ETA, pickup/dropoff options
4. On checkout, save selected quote id/raw payload with the order.
5. In admin order screen, add actions:
   - create delivery order
   - refresh delivery status
   - cancel shipment
6. Store provider tracking number and label URL in `shop_orders`.

## Data Fields Already Prepared

- `delivery_method`
- `delivery_status`
- `delivery_price`
- `city`
- `address`
- `raw_payload`
