import pytest

# pytest forces us to redefine the `mock` global function as a parameter of
# the test cases as that's how you request a fixture, so we disable this lint
# globally in this file.
# pylint: disable=redefined-outer-name


@pytest.fixture
def mock():
    # Setup
    my_obj = {"what": "fixture?!?"}

    # Yield the ready to be used fixture object
    yield my_obj

    # Cleanup
    # my_obj.clean_resources()


def test_something(mock):
    # response = mock.do_something()
    # assert response == "expectation"
    assert mock["what"] == "fixture?!?"
