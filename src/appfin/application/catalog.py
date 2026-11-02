"""Casos de uso dos cadastros: empresa, contas, categorias e contatos."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from appfin.domain.default_categories import default_categories
from appfin.domain.entities import Account, Category, Company, Contact
from appfin.domain.enums import AccountKind, TaxRegime
from appfin.domain.errors import BusinessRuleError, NotFoundError, ValidationError
from appfin.domain.repositories import UnitOfWork

DEFAULT_ACCOUNT_NAME = "Caixa do consultório"


class CatalogService:
    def __init__(self, uow: Callable[[], UnitOfWork], new_id: Callable[[], str]) -> None:
        self._uow = uow
        self._new_id = new_id

    # ------------------------------------------------------------------ empresa
    def get_company(self) -> Company | None:
        with self._uow() as uow:
            return uow.company.get()

    def save_company(self, company: Company) -> Company:
        with self._uow() as uow:
            saved = uow.company.update(company) if company.version else uow.company.add(company)
            uow.commit()
        return saved

    def initialize_defaults(self, regime: TaxRegime) -> None:
        """Categorias padrão do consultório e uma conta caixa. Idempotente (só se estiver vazio)."""
        with self._uow() as uow:
            if uow.categories.count() == 0:
                for group_name, kind, dre_group, children in default_categories(regime):
                    group = uow.categories.add(
                        Category(self._new_id(), group_name, kind, dre_group=dre_group)
                    )
                    for child in children:
                        uow.categories.add(
                            Category(
                                self._new_id(), child, kind, parent_id=group.id, dre_group=dre_group
                            )
                        )
            if not uow.accounts.list(include_archived=True):
                uow.accounts.add(Account(self._new_id(), DEFAULT_ACCOUNT_NAME, AccountKind.CASH))
            uow.commit()

    # ------------------------------------------------------------------ contas
    def list_accounts(self, *, include_archived: bool = False) -> list[Account]:
        with self._uow() as uow:
            return uow.accounts.list(include_archived=include_archived)

    def save_account(self, account: Account) -> Account:
        with self._uow() as uow:
            if account.version:
                saved = uow.accounts.update(account)
            else:
                saved = uow.accounts.add(replace(account, id=account.id or self._new_id()))
            uow.commit()
        return saved

    def set_account_archived(self, account_id: str, archived: bool) -> Account:
        with self._uow() as uow:
            account = _required(uow.accounts.get(account_id))
            if archived and len([a for a in uow.accounts.list() if not a.archived]) <= 1:
                raise BusinessRuleError("É preciso manter ao menos uma conta ativa.")
            saved = uow.accounts.update(replace(account, archived=archived))
            uow.commit()
        return saved

    # ------------------------------------------------------------------ categorias
    def list_categories(self, *, include_archived: bool = False) -> list[Category]:
        with self._uow() as uow:
            return uow.categories.list(include_archived=include_archived)

    def save_category(self, category: Category) -> Category:
        with self._uow() as uow:
            if category.parent_id is not None:
                parent = uow.categories.get(category.parent_id)
                if parent is None or not parent.is_group:
                    raise ValidationError("parent_id", "Escolha um grupo válido.")
                has_children = any(
                    c.parent_id == category.id for c in uow.categories.list(include_archived=True)
                )
                if has_children:
                    raise ValidationError(
                        "parent_id", "Um grupo com categorias não pode virar subcategoria."
                    )
            if category.version:
                saved = uow.categories.update(category)
            else:
                saved = uow.categories.add(replace(category, id=category.id or self._new_id()))
            uow.commit()
        return saved

    def set_category_archived(self, category_id: str, archived: bool) -> Category:
        with self._uow() as uow:
            category = _required(uow.categories.get(category_id))
            saved = uow.categories.update(replace(category, archived=archived))
            uow.commit()
        return saved

    # ------------------------------------------------------------------ contatos
    def search_contacts(self, text: str = "", *, limit: int = 200) -> list[Contact]:
        with self._uow() as uow:
            return uow.contacts.search(text, limit=limit)

    def get_contact(self, contact_id: str) -> Contact:
        with self._uow() as uow:
            return _required(uow.contacts.get(contact_id))

    def save_contact(self, contact: Contact) -> Contact:
        with self._uow() as uow:
            if contact.version:
                saved = uow.contacts.update(contact)
            else:
                saved = uow.contacts.add(replace(contact, id=contact.id or self._new_id()))
            uow.commit()
        return saved

    def delete_contact(self, contact_id: str) -> None:
        with self._uow() as uow:
            _required(uow.contacts.get(contact_id))
            if uow.contacts.is_referenced(contact_id):
                raise BusinessRuleError(
                    "Este contato tem lançamentos e não pode ser excluído. Arquive-o."
                )
            uow.contacts.soft_delete(contact_id)
            uow.commit()


def _required[T](value: T | None) -> T:
    if value is None:
        raise NotFoundError("Registro não encontrado.")
    return value
