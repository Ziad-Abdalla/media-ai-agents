"""A thin wrapper around Odoo's XML-RPC API.

Odoo exposes two endpoints:
  /xmlrpc/2/common  -> log in, get a user id (uid)
  /xmlrpc/2/object  -> call any method on any model with execute_kw
"""

import xmlrpc.client

from . import config


class OdooClient:
    def __init__(self, url=config.ODOO_URL, db=config.ODOO_DB,
                 user=config.ODOO_USER, password=config.ODOO_PASSWORD):
        self.db, self.password = db, password
        common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
        self.uid = common.authenticate(db, user, password, {})
        if not self.uid:
            raise PermissionError(f"Odoo login failed for {user} on database {db}")
        self.models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object", allow_none=True)

    def call(self, model: str, method: str, *args, **kwargs):
        try:
            return self.models.execute_kw(self.db, self.uid, self.password,
                                          model, method, list(args), kwargs)
        except xmlrpc.client.Fault as e:
            # Some Odoo buttons (like button_cancel) return None, which XML-RPC can't send back.
            # The method already ran and was saved; only the reply failed. Treat it as success.
            if "cannot marshal None" in e.faultString:
                return None
            raise

    def search_read(self, model: str, domain: list, fields: list[str]) -> list[dict]:
        return self.call(model, "search_read", domain, fields=fields)

    def create(self, model: str, values: dict) -> int:
        return self.call(model, "create", values)

    def write(self, model: str, record_id: int, values: dict) -> bool:
        return self.call(model, "write", [record_id], values)
