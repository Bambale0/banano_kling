from typing import Any
from pydantic import BaseModel, EmailStr, Field
class RegisterIn(BaseModel): email:EmailStr; password:str=Field(min_length=8); full_name:str|None=None; organization_name:str
class LoginIn(BaseModel): email:EmailStr; password:str
class TenantIn(BaseModel): name:str; slug:str|None=None; billing_email:EmailStr|None=None
class BotCreate(BaseModel): token:str; display_name:str|None=None; set_webhook:bool=False
class BotConfigIn(BaseModel): language:str='ru'; tone_of_voice:str|None=None; brand_description:str|None=None; system_prompt:str|None=None; welcome_message:str|None=None; fallback_message:str|None=None; content_rules:dict[str,Any]={}; safety_rules:dict[str,Any]={}; generation_limits:dict[str,Any]={}; store_enabled:bool=True; analytics_enabled:bool=True
class GenerationCreate(BaseModel): bot_id:str|None=None; content_type:str='post'; prompt:str; source:str='dashboard'; idempotency_key:str|None=None
class ProductIn(BaseModel): category_id:str|None=None; sku:str|None=None; name:str; slug:str|None=None; description:str|None=None; short_description:str|None=None; price_amount:float; currency:str='RUB'; stock_quantity:int|None=0; stock_policy:str='track'; status:str='active'; attributes:dict[str,Any]={}; metadata:dict[str,Any]={}
class OrderItemIn(BaseModel): product_id:str; quantity:int=Field(gt=0)
class OrderCreate(BaseModel): bot_id:str|None=None; customer:dict[str,Any]; delivery:dict[str,Any]={}; items:list[OrderItemIn]
class CheckoutIn(BaseModel): plan_code:str; success_url:str|None=None; cancel_url:str|None=None
class TopUpIn(BaseModel): amount:float=Field(gt=0); provider:str='manual'
class EventIn(BaseModel): event_name:str; bot_id:str|None=None; entity_type:str|None=None; entity_id:str|None=None; properties:dict[str,Any]={}
