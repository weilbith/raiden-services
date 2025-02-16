from gevent import monkey

monkey.patch_all(subprocess=False, thread=False)

# isort: split

from typing import Dict, List

import click
import gevent
import structlog
from eth_utils import to_canonical_address
from jaeger_client import Config
from opentracing.scope_managers.gevent import GeventScopeManager
from requests_opentracing import SessionTracing
from web3 import HTTPProvider, Web3
from web3._utils.request import cache_session
from web3.contract import Contract

from pathfinding_service.api import PFSApi
from pathfinding_service.constants import DEFAULT_INFO_MESSAGE, PFS_DISCLAIMER, PFS_START_TIMEOUT
from pathfinding_service.service import PathfindingService
from raiden.settings import DEFAULT_NUMBER_OF_BLOCK_CONFIRMATIONS
from raiden.utils.typing import MYPY_ANNOTATION, BlockNumber, BlockTimeout, TokenAmount
from raiden_contracts.constants import (
    CONTRACT_ONE_TO_N,
    CONTRACT_TOKEN_NETWORK_REGISTRY,
    CONTRACT_USER_DEPOSIT,
)
from raiden_contracts.utils.type_aliases import PrivateKey
from raiden_libs.blockchain import get_web3_provider_info
from raiden_libs.cli import blockchain_options, common_options, setup_sentry
from raiden_libs.constants import (
    CONFIRMATION_OF_UNDERSTANDING,
    DEFAULT_API_HOST,
    DEFAULT_API_PORT_PFS,
    DEFAULT_POLL_INTERVALL,
)
from raiden_libs.utils import to_checksum_address

log = structlog.get_logger(__name__)


@blockchain_options(
    contracts=[CONTRACT_TOKEN_NETWORK_REGISTRY, CONTRACT_USER_DEPOSIT, CONTRACT_ONE_TO_N]
)
@click.command()
@click.option(
    "--host", default=DEFAULT_API_HOST, type=str, help="The host to use for serving the REST API"
)
@click.option(
    "--port",
    default=DEFAULT_API_PORT_PFS,
    type=int,
    help="The port to use for serving the REST API",
)
@click.option(
    "--service-fee",
    default=0,
    type=click.IntRange(min=0),
    help="Service fee which is required before processing requests",
)
@click.option(
    "--confirmations",
    default=DEFAULT_NUMBER_OF_BLOCK_CONFIRMATIONS,
    type=click.IntRange(min=0),
    help="Number of block confirmations to wait for",
)
@click.option("--operator", default="John Doe", type=str, help="Name of the service operator")
@click.option(
    "--info-message",
    default=DEFAULT_INFO_MESSAGE,
    type=str,
    help="Place for a personal message to the customers",
)
@click.option(
    "--matrix-server",
    type=str,
    multiple=True,
    help="Use this matrix server instead of the default ones. Include protocol in argument.",
)
@click.option(
    "--accept-disclaimer",
    type=bool,
    default=False,
    help="Bypass the experimental software disclaimer prompt",
    is_flag=True,
)
@click.option("--enable-debug", is_flag=True, hidden=True)
@click.option("--enable-tracing", is_flag=True, hidden=True)
@click.option("--tracing-sampler", default="const", hidden=True)
@click.option("--tracing-param", default="1", hidden=True)
@common_options("raiden-pathfinding-service")
def main(  # pylint: disable=too-many-arguments,too-many-locals
    private_key: PrivateKey,
    state_db: str,
    web3: Web3,
    contracts: Dict[str, Contract],
    start_block: BlockNumber,
    confirmations: BlockTimeout,
    host: str,
    port: int,
    service_fee: TokenAmount,
    operator: str,
    info_message: str,
    enable_debug: bool,
    matrix_server: List[str],
    accept_disclaimer: bool,
    enable_tracing: bool,
    tracing_sampler: str,
    tracing_param: str,
) -> int:
    """The Pathfinding service for the Raiden Network."""
    log.info("Starting Raiden Pathfinding Service")
    click.secho(PFS_DISCLAIMER, fg="yellow")
    if not accept_disclaimer:
        click.confirm(CONFIRMATION_OF_UNDERSTANDING, abort=True)
    log.info("Using RPC endpoint", rpc_url=get_web3_provider_info(web3))
    hex_addresses = {
        name: to_checksum_address(contract.address) for name, contract in contracts.items()
    }
    log.info("Contract information", addresses=hex_addresses, start_block=start_block)

    if enable_tracing:
        tracing_config = Config(
            config={"sampler": {"type": tracing_sampler, "param": tracing_param}, "logging": True},
            service_name="pfs",
            scope_manager=GeventScopeManager(),
            validate=True,
        )
        # Tracer is stored in `opentracing.tracer`
        tracing_config.initialize_tracer()

        assert isinstance(web3.provider, HTTPProvider), MYPY_ANNOTATION
        assert web3.provider.endpoint_uri is not None, MYPY_ANNOTATION
        # Set `Web3` requests Session to use `SessionTracing`
        cache_session(
            web3.provider.endpoint_uri,
            SessionTracing(propagate=False, span_tags={"target": "ethnode"}),
        )

    service = None
    api = None
    try:
        service = PathfindingService(
            web3=web3,
            contracts=contracts,
            sync_start_block=start_block,
            required_confirmations=confirmations,
            private_key=private_key,
            poll_interval=DEFAULT_POLL_INTERVALL,
            db_filename=state_db,
            matrix_servers=matrix_server,
            enable_tracing=enable_tracing,
        )
        service.start()
        log.debug("Waiting for service to start before accepting API requests")
        try:
            service.startup_finished.get(timeout=PFS_START_TIMEOUT)
        except gevent.Timeout:
            raise Exception("PFS did not start within time.")

        log.debug("Starting API")
        api = PFSApi(
            pathfinding_service=service,
            service_fee=service_fee,
            debug_mode=enable_debug,
            one_to_n_address=to_canonical_address(contracts[CONTRACT_ONE_TO_N].address),
            operator=operator,
            info_message=info_message,
            enable_tracing=enable_tracing,
        )
        api.run(host=host, port=port)

        service.get()
    except (KeyboardInterrupt, SystemExit):
        print("Exiting...")
    finally:
        log.info("Stopping Pathfinding Service...")
        if api:
            api.stop()
        if service:
            service.stop()

    return 0


if __name__ == "__main__":
    setup_sentry(enable_flask_integration=True)
    main(auto_envvar_prefix="PFS")  # pragma: no cover
