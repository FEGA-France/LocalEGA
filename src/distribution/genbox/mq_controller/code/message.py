import json

class FEGAMessage:

    __parsed = None
    __content = None
    __message = None
    __type = None
    __correlation_id = None

    def __init__(self, message):
        self.__message = message

    def __getattr__(self, item):
        return getattr(self.__message, item)

    @property
    def content(self):
        if self.__content is None:
            self.__content = self.body.decode()
        return self.__content

    @property
    def parsed(self):
        """Return a JSON deserializing of itself."""
        if self.__parsed is None:
            try:
                self.__parsed = json.loads(self.content)
            except Exception as e:
                # self.__parsed = {} # make it empty so that message.parsed.get(...) won't fail
                raise
        return self.__parsed

    @property
    def job_type(self):
        if not self.__type:
            self.__type = self.parsed.get('type', None)
        return self.__type

    @property
    def correlation_id(self):
        if not self.__correlation_id:
            try:
                self.__correlation_id = self.__message.header.properties.correlation_id
            except KeyError as e:
                self.__correlation_id = None
        return self.__correlation_id

    def __str__(self):
        try:
            return f'<Message {self.delivery.delivery_tag} | job: {self.job_type}>'
        except Exception as e:
            return f'<Message {self.delivery.delivery_tag} | job: None>'

