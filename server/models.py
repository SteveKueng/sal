import plistlib
import secrets
import string
from datetime import datetime
from xml.parsers.expat import ExpatError

import pytz
from dateutil.parser import parse
from ulid2 import generate_ulid_as_uuid

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

from utils import text_utils


OS_CHOICES = (
    ('Darwin', 'macOS'),
    ('Windows', 'Windows'),
    ('Linux', 'Linux'),
    ('ChromeOS', 'Chrome OS'),
)

REPORT_CHOICES = (
    ('base64', 'base64'),
    ('base64bz2', 'base64bz2'),
    ('bz2', 'bz2'),
)


class ProfileLevel():
    stats_only = 'SO'
    read_only = 'RO'
    read_write = 'RW'
    global_admin = 'GA'


def GenerateKey():
    key = ''.join(secrets.choice(string.ascii_lowercase + string.digits) for x in range(128))
    try:
        MachineGroup.objects.get(key=key)
        return GenerateKey()
    except MachineGroup.DoesNotExist:
        return key


def GenerateAPIKey():
    key = ''.join(secrets.choice(string.ascii_lowercase + string.digits) for x in range(24))
    try:
        ApiKey.objects.get(public_key=key)
        return GenerateAPIKey()
    except ApiKey.DoesNotExist:
        return key


class UserProfile(models.Model):
    user = models.OneToOneField(User, unique=True, on_delete=models.CASCADE)

    LEVEL_CHOICES = (
        ('SO', 'Stats Only'),
        ('RO', 'Read Only'),
        ('RW', 'Read Write'),
        ('GA', 'Global Admin'),
    )
    level = models.CharField(max_length=2, choices=LEVEL_CHOICES, default='RO')

    def __str__(self):
        return self.user.username


User.userprofile = property(lambda u: UserProfile.objects.get_or_create(user=u)[0])


class BusinessUnit(models.Model):
    name = models.CharField(max_length=100)
    users = models.ManyToManyField(User, blank=True)

    def __str__(self):
        return self.name

    @classmethod
    def display_name(cls):
        return text_utils.class_to_title(cls.__name__)

    class Meta:
        ordering = ['name']


class MachineGroup(models.Model):
    business_unit = models.ForeignKey(BusinessUnit, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    key = models.CharField(db_index=True, max_length=255, unique=True,
                           blank=True, null=True, editable=False)

    def save(self, **kwargs):
        if not self.id:
            self.key = GenerateKey()
        super(MachineGroup, self).save()

    def __str__(self):
        return self.name

    @classmethod
    def display_name(cls):
        return text_utils.class_to_title(cls.__name__)

    class Meta:
        ordering = ['name']


class DeployedManager(models.Manager):
    def get_queryset(self):
        return super(DeployedManager, self).get_queryset().filter(deployed=True)


class Machine(models.Model):
    id = models.BigAutoField(primary_key=True)
    machine_group = models.ForeignKey(MachineGroup, on_delete=models.CASCADE)
    sal_version = models.CharField(db_index=True, null=True, blank=True, max_length=255)
    deployed = models.BooleanField(default=True)
    broken_client = models.BooleanField(default=False)
    last_checkin = models.DateTimeField(db_index=True, blank=True, null=True)
    first_checkin = models.DateTimeField(db_index=True, blank=True, null=True, auto_now_add=True)

    serial = models.CharField(db_index=True, max_length=100, unique=True)
    hostname = models.CharField(max_length=256, null=True, blank=True)
    operating_system = models.CharField(db_index=True, max_length=256, null=True, blank=True)
    memory = models.CharField(db_index=True, max_length=256, null=True, blank=True)
    memory_kb = models.IntegerField(db_index=True, default=0)
    hd_space = models.BigIntegerField(db_index=True, null=True, blank=True)
    hd_total = models.BigIntegerField(db_index=True, null=True, blank=True)
    hd_percent = models.CharField(max_length=256, null=True, blank=True)
    console_user = models.CharField(max_length=256, null=True, blank=True)
    machine_model = models.CharField(db_index=True, max_length=100, null=True, blank=True)
    machine_model_id = models.BigIntegerField(db_index=True, null=True, blank=True)
    machine_model_friendly = models.CharField(db_index=True, max_length=256, null=True, blank=True)
    cpu_type = models.CharField(max_length=256, null=True, blank=True)
    cpu_speed = models.CharField(max_length=256, null=True, blank=True)
    os_family = models.CharField(db_index=True, max_length=256,
                                 choices=OS_CHOICES, verbose_name="OS Family", default="Darwin")

    munki_version = models.CharField(db_index=True, max_length=256, null=True, blank=True)
    manifest = models.CharField(db_index=True, max_length=256, null=True, blank=True)

    objects = models.Manager()  # The default manager.
    deployed_objects = DeployedManager()

    def get_fields(self):
        return [(field.name, field.value_to_string(self)) for field in Machine._meta.fields]

    def __str__(self):
        if self.hostname:
            return self.hostname
        else:
            return self.serial

    @classmethod
    def display_name(cls):
        return text_utils.class_to_title(cls.__name__)

    class Meta:
        ordering = ['hostname']


GROUP_NAMES = {
    'all': None,
    'machine_group': MachineGroup,
    'business_unit': BusinessUnit,
    'machine': Machine}


class PluginScriptSubmission(models.Model):
    id = models.BigAutoField(primary_key=True)
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE)
    plugin = models.CharField(max_length=255)
    historical = models.BooleanField(default=False)
    recorded = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return '%s: %s' % (self.machine, self.plugin)

    class Meta:
        ordering = ['recorded', 'plugin']


class PluginScriptRow(models.Model):
    id = models.BigAutoField(primary_key=True)
    submission = models.ForeignKey(PluginScriptSubmission, on_delete=models.CASCADE)
    pluginscript_name = models.TextField()
    pluginscript_data = models.TextField(blank=True, null=True)
    pluginscript_data_string = models.TextField(blank=True, null=True)
    pluginscript_data_int = models.IntegerField(default=0)
    pluginscript_data_date = models.DateTimeField(blank=True, null=True)
    submission_and_script_name = models.TextField()

    def save(self):
        try:
            self.pluginscript_data_int = int(self.pluginscript_data)
        except (ValueError, TypeError):
            self.pluginscript_data_int = 0

        self.pluginscript_data_string = str(self.pluginscript_data)

        try:
            date_data = parse(self.pluginscript_data)
            if not date_data.tzinfo:
                date_data = date_data.replace(tzinfo=pytz.UTC)
            self.pluginscript_data_date = date_data
        except ValueError:
            # Try converting it to an int if we're here
            try:
                if int(self.pluginscript_data) != 0:

                    try:
                        self.pluginscript_data_date = datetime.fromtimestamp(
                            int(self.pluginscript_data), tz=pytz.UTC)
                    except (ValueError, TypeError):
                        self.pluginscript_data_date = None
                else:
                    self.pluginscript_data_date = None
            except (ValueError, TypeError):
                self.pluginscript_data_date = None

        super(PluginScriptRow, self).save()

    def __str__(self):
        return '%s: %s' % (self.pluginscript_name, self.pluginscript_data)

    class Meta:
        ordering = ['pluginscript_name']


class Plugin(models.Model):
    name = models.CharField(max_length=255, unique=True)
    order = models.IntegerField()

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['order']


class MachineDetailPlugin(models.Model):
    name = models.CharField(max_length=255, unique=True)
    order = models.IntegerField()

    def __str_(self):
        return self.name

    class Meta:
        ordering = ['order']


class Report(models.Model):
    name = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']


class SalSetting(models.Model):
    name = models.CharField(max_length=255, unique=True)
    value = models.TextField()

    def __str__(self):
        return self.name


class ApiKey(models.Model):
    public_key = models.CharField(max_length=255)
    private_key = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    has_been_seen = models.BooleanField(default=False)
    read_write = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if not self.id:
            self.public_key = GenerateAPIKey()
            self.private_key = ''.join(secrets.choice(
                string.ascii_lowercase + string.digits) for x in range(64))
        super(ApiKey, self).save(*args, **kwargs)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']
        unique_together = ("public_key", "private_key")


class FriendlyNameCache(models.Model):
    serial_stub = models.CharField(max_length=5)
    friendly_name = models.CharField(max_length=255)


class ManagementSource(models.Model):
    id = models.UUIDField(default=generate_ulid_as_uuid, primary_key=True)
    name = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return self.name


STATUS_CHOICES = (
    ('PRESENT', 'Present'),
    ('ABSENT', 'Absent'),
    ('PENDING', 'Pending'),
    ('ERROR', 'Error'),
    ('UNKNOWN', 'Unknown'),
)


class ManagedItem(models.Model):
    id = models.UUIDField(default=generate_ulid_as_uuid, primary_key=True)
    name = models.CharField(max_length=255)
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE)
    management_source = models.ForeignKey(ManagementSource, on_delete=models.CASCADE)
    date_managed = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=7, choices=STATUS_CHOICES, default='UNKNOWN')
    data = models.TextField(editable=True, null=True)

    class Meta:
        unique_together = (("machine", "name", "management_source"),)
        ordering = ['id']


class ManagedItemHistory(models.Model):
    id = models.UUIDField(default=generate_ulid_as_uuid, primary_key=True)
    recorded = models.DateTimeField()
    name = models.CharField(max_length=255)
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE)
    management_source = models.ForeignKey(ManagementSource, on_delete=models.CASCADE)
    status = models.CharField(max_length=7, choices=STATUS_CHOICES, default='UNKNOWN')

    class Meta:
        unique_together = (("machine", "name", "management_source", "recorded"),)
        ordering = ['-recorded']

    def __str__(self):
        return (
            f"{self.machine}: {self.management_source.name} {self.name} {self.status} "
            f"{self.recorded}")


class Fact(models.Model):
    id = models.BigAutoField(primary_key=True)
    machine = models.ForeignKey(Machine, related_name='facts', on_delete=models.CASCADE)
    management_source = models.ForeignKey(
        ManagementSource, related_name='facts', on_delete=models.CASCADE, null=True)
    fact_name = models.TextField()
    fact_data = models.TextField()

    def __str__(self):
        return '%s: %s' % (self.fact_name, self.fact_data)

    class Meta:
        ordering = ['fact_name']


class HistoricalFact(models.Model):
    id = models.BigAutoField(primary_key=True)
    machine = models.ForeignKey(Machine, related_name='historical_facts', on_delete=models.CASCADE)
    management_source = models.ForeignKey(
        ManagementSource, related_name='historical_facts', on_delete=models.CASCADE, null=True)
    fact_name = models.CharField(max_length=255)
    fact_data = models.TextField()
    fact_recorded = models.DateTimeField()

    def __str__(self):
        return self.fact_name

    class Meta:
        ordering = ['fact_name', 'fact_recorded']


class Message(models.Model):
    id = models.BigAutoField(primary_key=True)
    machine = models.ForeignKey(Machine, related_name='messages', on_delete=models.CASCADE)
    management_source = models.ForeignKey(
        ManagementSource, related_name='messages', on_delete=models.CASCADE, null=True)
    text = models.TextField(blank=True, null=True)
    date = models.DateTimeField(default=timezone.now)
    MESSAGE_TYPES = (
        ('ERROR', 'Error'),
        ('WARNING', 'Warning'),
        ('OTHER', 'Other'),
        ('DEBUG', 'Debug'),
    )
    message_type = models.CharField(max_length=7, choices=MESSAGE_TYPES, default='OTHER')
