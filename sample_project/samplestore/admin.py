from django.contrib import admin
from samplestore.models import Invoice, Item, Customer, CustomerProfile, \
CustomerPaymentProfile, Address

admin.site.register(Invoice)
admin.site.register(Item)
admin.site.register(Customer)
admin.site.register(CustomerProfile)
admin.site.register(CustomerPaymentProfile)
admin.site.register(Address)
