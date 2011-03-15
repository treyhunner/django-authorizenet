from django.db import models
from django.db.models.signals import post_save

from django.contrib.auth.models import User
from django.contrib.localflavor.us.models import PhoneNumberField, USStateField

from authorizenet.signals import payment_was_successful, payment_was_flagged
from authorizenet.cim import add_profile, get_profile, \
        update_payment_profile, create_payment_profile, delete_payment_profile
from django.forms.models import model_to_dict
from samplestore.errors import BillingError


ADDRESS_CHOICES = (
     ('billing', 'Billing'),
     ('shipping', 'Shipping'),
)


class Customer(models.Model):
    user = models.ForeignKey(User)
    shipping_same_as_billing = models.BooleanField(default=True)

    def __unicode__(self):
        return self.user.username


class CustomerProfileManager(models.Manager):
    def create(self, **kwargs):
        """Create new Authorize.NET customer profile"""
        user = kwargs.get('user')
        payment_data = kwargs.pop('payment_data', {})
        billing_data = kwargs.pop('billing_data', {})
        # Create the customer profile with Authorize.NET CIM call
        response, profile_id, payment_profile_ids = add_profile(user.pk,
                payment_data, billing_data)
        if not response.success:
            raise BillingError()
        kwargs['profile_id'] = profile_id
        # Store customer profile data locally
        instance = super(CustomerProfileManager, self).create(**kwargs)

        # Store customer payment profile data locally
        for payment_profile_id in payment_profile_ids:
            CustomerPaymentProfile.objects.create(
                customer_profile=instance,
                payment_profile_id=payment_profile_id,
                billing_data=billing_data,
                payment_data=payment_data,
                make_cim_request=False,
            )

        return instance


class CustomerProfile(models.Model):

    """Authorize.NET customer profile"""

    user = models.ForeignKey(User, unique=True)
    profile_id = models.CharField(max_length=50)

    def sync(self):
        """Overwrite local customer profile data with remote data"""
        response, payment_profiles = get_profile(self.profile_id)
        if not response.success:
            raise BillingError()
        for payment_profile in payment_profiles:
            instance, created = CustomerPaymentProfile.objects.get_or_create(
                customer_profile=self,
                payment_profile_id=payment_profile['payment_profile_id']
            )
            instance.sync(payment_profile)

    objects = CustomerProfileManager()


class CustomerPaymentProfileManager(models.Manager):
    def create(self, **kwargs):
        """Create new Authorize.NET customer payment profile"""
        customer_profile = kwargs.get('customer_profile')
        payment_data = kwargs.pop('payment_data', {})
        billing_data = kwargs.pop('billing_data', {})
        if kwargs.pop('make_cim_request', True):
            # Create the customer payment profile with Authorize.NET CIM call
            response, payment_profile_id = create_payment_profile(
                    customer_profile.profile_id, payment_data, billing_data)
            if not response.success:
                raise BillingError()
            kwargs['payment_profile_id'] = payment_profile_id
        kwargs.update(billing_data)
        kwargs.update(payment_data)
        kwargs.pop('expiration_date')
        kwargs.pop('card_code')
        if 'card_number' in kwargs:
            kwargs['card_number'] = "XXXX%s" % kwargs['card_number'][-4:]
        return super(CustomerPaymentProfileManager, self).create(**kwargs)


class CustomerPaymentProfile(models.Model):

    """Authorize.NET customer payment profile"""

    customer_profile = models.ForeignKey('CustomerProfile',
            related_name='payment_profiles')
    first_name = models.CharField(max_length=50, blank=True)
    last_name = models.CharField(max_length=50, blank=True)
    company = models.CharField(max_length=50, blank=True)
    address = models.CharField(max_length=60, blank=True)
    city = models.CharField(max_length=40, blank=True)
    state = models.CharField(max_length=40, blank=True)
    zip = models.CharField(max_length=20, blank=True, verbose_name="ZIP")
    country = models.CharField(max_length=60, blank=True)
    phone = models.CharField(max_length=25, blank=True)
    fax = models.CharField(max_length=25, blank=True)
    payment_profile_id = models.CharField(max_length=50)
    card_number = models.CharField(max_length=16, blank=True)

    def raw_data(self):
        """Return data suitable for use in payment and billing forms"""
        return model_to_dict(self)

    def sync(self, data):
        """Overwrite local customer payment profile data with remote data"""
        for k, v in data.get('billing', {}).items():
            setattr(self, k, v)
        self.card_number = data.get('credit_card', {}).get('card_number',
                self.card_number)
        self.save()

    def delete(self):
        """Delete the customer payment profile remotely and locally"""
        delete_payment_profile(self.customer_profile.profile_id,
                self.payment_profile_id)

    def update(self, payment_data, billing_data):
        """Update the customer payment profile remotely and locally"""
        response = update_payment_profile(self.customer_profile.profile_id,
                self.payment_profile_id, payment_data, billing_data)
        if not response.success:
            raise BillingError()
        for k, v in billing_data.items():
            setattr(self, k, v)
        for k, v in payment_data.items():
            # Do not store expiration date and mask credit card number
            if k != 'expiration_date' and k != 'card_code':
                if k == 'card_number':
                    v = "XXXX%s" % v[-4:]
                setattr(self, k, v)
        self.save()

    def __unicode__(self):
        return self.card_number

    objects = CustomerPaymentProfileManager()


class Address(models.Model):
    type = models.CharField(max_length=10, choices=ADDRESS_CHOICES)
    customer = models.ForeignKey(Customer)
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    company = models.CharField(max_length=50, blank=True)
    address = models.CharField(max_length=60)
    city = models.CharField(max_length=40)
    state = USStateField()
    zip_code = models.CharField(max_length=20)
    phone = PhoneNumberField(blank=True)
    fax = PhoneNumberField(blank=True)

    def __unicode__(self):
        return self.customer.user.username


class Item(models.Model):
    title = models.CharField(max_length=55)
    price = models.DecimalField(max_digits=8, decimal_places=2)

    def __unicode__(self):
        return self.title


class Invoice(models.Model):
    customer = models.ForeignKey(Customer)
    item = models.ForeignKey(Item)

    def __unicode__(self):
        return u"<Invoice: %d - %s>" % (self.id, self.customer.user.username)


def create_customer_profile(sender, instance=None, **kwargs):
    if instance is None:
        return
    profile, created = Customer.objects.get_or_create(user=instance)


post_save.connect(create_customer_profile, sender=User)


def successfull_payment(sender, **kwargs):
    response = sender
    # do something with the response


def flagged_payment(sender, **kwargs):
    response = sender
    # do something with the response


payment_was_successful.connect(successfull_payment)
payment_was_flagged.connect(flagged_payment)
