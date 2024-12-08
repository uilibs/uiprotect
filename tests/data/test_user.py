from datetime import datetime

from uiprotect.data.user import Keyring, Keyrings, UlpUser, UlpUsers


def test_ulp_user_creation():
    user = UlpUser(
        id="1",
        ulp_id="ulp1",
        first_name="John",
        last_name="Doe",
        full_name="John Doe",
        avatar="avatar_url",
        status="active",
    )
    assert user.id == "1"
    assert user.ulp_id == "ulp1"
    assert user.first_name == "John"
    assert user.last_name == "Doe"
    assert user.full_name == "John Doe"
    assert user.avatar == "avatar_url"
    assert user.status == "active"


def test_ulp_users_add_and_remove():
    users = UlpUsers()
    user = UlpUser(
        id="1",
        ulp_id="ulp1",
        first_name="John",
        last_name="Doe",
        full_name="John Doe",
        avatar="avatar_url",
        status="active",
    )
    users.add(user)
    assert users.by_id("1") == user
    assert users.by_ulp_id("ulp1") == user

    users.remove(user)
    assert users.by_id("1") is None
    assert users.by_ulp_id("ulp1") is None


def test_keyring_creation():
    keyring = Keyring(
        id="1",
        device_type="type1",
        device_id="device1",
        registry_type="reg_type1",
        registry_id="reg_id1",
        last_activity=datetime.now(),
        ulp_user="ulp1",
    )
    assert keyring.id == "1"
    assert keyring.device_type == "type1"
    assert keyring.device_id == "device1"
    assert keyring.registry_type == "reg_type1"
    assert keyring.registry_id == "reg_id1"
    assert keyring.ulp_user == "ulp1"


def test_keyrings_add_and_remove():
    keyrings = Keyrings()
    keyring = Keyring(
        id="1",
        device_type="type1",
        device_id="device1",
        registry_type="reg_type1",
        registry_id="reg_id1",
        last_activity=datetime.now(),
        ulp_user="ulp1",
    )
    keyrings.add(keyring)
    assert keyrings.by_id("1") == keyring
    assert keyrings.by_registry_id("reg_id1") == keyring
    assert keyrings.by_ulp_id("ulp1") == keyring

    keyrings.remove(keyring)
    assert keyrings.by_id("1") is None
    assert keyrings.by_registry_id("reg_id1") is None
    assert keyrings.by_ulp_id("ulp1") is None


def test_ulp_users_replace_with_list():
    users = UlpUsers()
    user1 = UlpUser(
        id="1",
        ulp_id="ulp1",
        first_name="John",
        last_name="Doe",
        full_name="John Doe",
        avatar="avatar_url",
        status="active",
    )
    user2 = UlpUser(
        id="2",
        ulp_id="ulp2",
        first_name="Jane",
        last_name="Doe",
        full_name="Jane Doe",
        avatar="avatar_url",
        status="inactive",
    )
    users.replace_with_list([user1, user2])
    assert users.by_id("1") == user1
    assert users.by_id("2") == user2
    assert users.by_ulp_id("ulp1") == user1
    assert users.by_ulp_id("ulp2") == user2


def test_keyrings_replace_with_list():
    keyrings = Keyrings()
    keyring1 = Keyring(
        id="1",
        device_type="type1",
        device_id="device1",
        registry_type="reg_type1",
        registry_id="reg_id1",
        last_activity=datetime.now(),
        ulp_user="ulp1",
    )
    keyring2 = Keyring(
        id="2",
        device_type="type2",
        device_id="device2",
        registry_type="reg_type2",
        registry_id="reg_id2",
        last_activity=datetime.now(),
        ulp_user="ulp2",
    )
    keyrings.replace_with_list([keyring1, keyring2])
    assert keyrings.by_id("1") == keyring1
    assert keyrings.by_id("2") == keyring2
    assert keyrings.by_registry_id("reg_id1") == keyring1
    assert keyrings.by_registry_id("reg_id2") == keyring2
    assert keyrings.by_ulp_id("ulp1") == keyring1
    assert keyrings.by_ulp_id("ulp2") == keyring2


def test_keyrings_equality():
    keyrings1 = Keyrings()
    keyring1 = Keyring(
        id="1",
        device_type="type1",
        device_id="device1",
        registry_type="reg_type1",
        registry_id="reg_id1",
        last_activity=datetime.now(),
        ulp_user="ulp1",
    )
    keyring2 = Keyring(
        id="2",
        device_type="type2",
        device_id="device2",
        registry_type="reg_type2",
        registry_id="reg_id2",
        last_activity=datetime.now(),
        ulp_user="ulp2",
    )
    keyrings1.add(keyring1)
    keyrings1.add(keyring2)

    keyrings2 = Keyrings()
    keyrings2.add(keyring1)
    keyrings2.add(keyring2)

    assert keyrings1 == keyrings2

    keyrings3 = Keyrings()
    keyring3 = Keyring(
        id="3",
        device_type="type3",
        device_id="device3",
        registry_type="reg_type3",
        registry_id="reg_id3",
        last_activity=datetime.now(),
        ulp_user="ulp3",
    )
    keyrings3.add(keyring3)

    assert keyrings1 != keyrings3


def test_keyrings_eq_not_implemented():
    keyrings = Keyrings()
    assert keyrings.__eq__(object()) == NotImplemented


def test_ulp_users_eq_not_implemented():
    users = UlpUsers()
    assert users.__eq__(object()) == NotImplemented


def test_ulp_users_equality():
    users1 = UlpUsers()
    user1 = UlpUser(
        id="1",
        ulp_id="ulp1",
        first_name="John",
        last_name="Doe",
        full_name="John Doe",
        avatar="avatar_url",
        status="active",
    )
    user2 = UlpUser(
        id="2",
        ulp_id="ulp2",
        first_name="Jane",
        last_name="Doe",
        full_name="Jane Doe",
        avatar="avatar_url",
        status="inactive",
    )
    users1.add(user1)
    users1.add(user2)

    users2 = UlpUsers()
    users2.add(user1)
    users2.add(user2)

    assert users1 == users2

    users3 = UlpUsers()
    user3 = UlpUser(
        id="3",
        ulp_id="ulp3",
        first_name="Jim",
        last_name="Beam",
        full_name="Jim Beam",
        avatar="avatar_url",
        status="active",
    )
    users3.add(user3)

    assert users1 != users3

def test_ulp_users_as_list():
        users = UlpUsers()
        user1 = UlpUser(
            id="1",
            ulp_id="ulp1",
            first_name="John",
            last_name="Doe",
            full_name="John Doe",
            avatar="avatar_url",
            status="active",
        )
        user2 = UlpUser(
            id="2",
            ulp_id="ulp2",
            first_name="Jane",
            last_name="Doe",
            full_name="Jane Doe",
            avatar="avatar_url",
            status="inactive",
        )
        users.add(user1)
        users.add(user2)
        user_list = users.as_list()
        assert len(user_list) == 2
        assert user1 in user_list
        assert user2 in user_list

