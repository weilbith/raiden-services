# pylint: disable=redefined-outer-name
import socket
from typing import Generator, Iterator
from unittest.mock import Mock

import pytest
from eth_typing import BlockNumber
from eth_utils import to_checksum_address
from tests.libs.mocks.web3 import Web3Mock

from monitoring_service.api import MsApi
from monitoring_service.service import MonitoringService
from pathfinding_service.constants import API_PATH
from raiden.utils.typing import BlockTimeout
from raiden_contracts.constants import (
    CONTRACT_MONITORING_SERVICE,
    CONTRACT_SERVICE_REGISTRY,
    CONTRACT_TOKEN_NETWORK_REGISTRY,
    CONTRACT_USER_DEPOSIT,
)
from raiden_libs.constants import DEFAULT_API_HOST


@pytest.fixture(scope="session")
def free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("localhost", 0))  # binding to port 0 will choose a free socket
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture(scope="session")
def api_url(free_port: int) -> str:
    return "http://localhost:{}{}".format(free_port, API_PATH)


@pytest.fixture
def monitoring_service_mock() -> Generator[MonitoringService, None, None]:
    web3_mock = Web3Mock()

    mock_udc = Mock(address=bytes([8] * 20))
    mock_udc.functions.effectiveBalance.return_value.call.return_value = 10000
    mock_udc.functions.token.return_value.call.return_value = to_checksum_address(bytes([7] * 20))
    ms = MonitoringService(
        web3=web3_mock,
        private_key="3a1076bf45ab87712ad64ccb3b10217737f7faacbf2872e88fdd9a537d8fe266",
        db_filename=":memory:",
        contracts={
            CONTRACT_TOKEN_NETWORK_REGISTRY: Mock(address=bytes([9] * 20)),
            CONTRACT_USER_DEPOSIT: mock_udc,
            CONTRACT_MONITORING_SERVICE: Mock(address=bytes([1] * 20)),
            CONTRACT_SERVICE_REGISTRY: Mock(address=bytes([2] * 20)),
        },
        sync_start_block=BlockNumber(0),
        required_confirmations=BlockTimeout(0),
        poll_interval=0,
    )

    yield ms


@pytest.fixture
def ms_api_sut(monitoring_service_mock: MonitoringService, free_port: int) -> Iterator[MsApi]:
    api = MsApi(monitoring_service=monitoring_service_mock, operator="")
    api.run(host=DEFAULT_API_HOST, port=free_port)
    yield api
    api.stop()
