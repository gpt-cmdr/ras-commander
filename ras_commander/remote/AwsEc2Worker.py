"""
AwsEc2Worker - AWS EC2 cloud compute worker.

This module implements the AwsEc2Worker class for executing HEC-RAS on
AWS EC2 instances.

IMPLEMENTATION STATUS: STUB - Future Development

Requirements:
    pip install ras-commander[remote-aws]
    # or: pip install boto3
"""

from dataclasses import dataclass
from typing import Optional

from .RasWorker import RasWorker
from ..LoggingConfig import get_logger

logger = get_logger(__name__)


def check_aws_dependencies():
    """
    Check if boto3 is available, raise clear error if not.

    This function is called lazily only when AWS functionality is actually used.
    """
    try:
        import boto3
        return boto3
    except ImportError:
        raise ImportError(
            "AWS EC2 worker requires boto3.\n"
            "Install with: pip install ras-commander[remote-aws]\n"
            "Or: pip install boto3"
        )


@dataclass
class AwsEc2Worker(RasWorker):
    """
    AWS EC2 cloud compute worker.

    IMPLEMENTATION STATUS: STUB - Future Development

    IMPLEMENTATION NOTES:
    AWS EC2 enables elastic compute capacity for burst workloads and large-scale
    parallel execution without local hardware constraints.

    When implemented, this worker will:
    1. Use boto3 library for AWS API access
    2. Launch EC2 instances on-demand or use existing instances
    3. Deploy projects via S3 or direct instance connection
    4. Execute HEC-RAS on Windows EC2 instances
    5. Collect results to S3 and optionally terminate instances
    6. Support spot instances for cost optimization

    Required Parameters:
        - region: AWS region (e.g., "us-east-1")
        - instance_type: EC2 instance type (e.g., "c5.2xlarge")
        - ami_id: AMI with HEC-RAS pre-installed
        - key_name: EC2 key pair name
        - security_group: Security group ID
        - iam_role: IAM role for S3 access
        - s3_bucket: S3 bucket for project deployment
        - spot_instance: Use spot instances (default False)

    Usage Pattern:
        aws_worker = init_ras_worker(
            "aws_ec2",
            region="us-east-1",
            instance_type="c5.4xlarge",
            ami_id="ami-hecras-6.3-windows",
            key_name="my-keypair",
            security_group="sg-xxxxxxxxx",
            iam_role="HECRASExecutionRole",
            s3_bucket="my-ras-projects",
            spot_instance=True,
            ras_exe_path=r"C:\\Program Files\\HEC\\HEC-RAS\\6.3\\RAS.exe"
        )

    Dependencies:
        - boto3: AWS SDK for Python

    Cost Optimization Strategies:
        - Use spot instances for interruptible workloads
        - Terminate instances after execution
        - Use appropriate instance sizing
        - Store results in S3 Intelligent-Tiering
    """
    region: str = "us-east-1"
    instance_type: str = "c5.2xlarge"
    ami_id: str = None
    key_name: str = None
    security_group: str = None
    iam_role: str = None
    s3_bucket: str = None
    spot_instance: bool = False
    auto_terminate: bool = True

    def __post_init__(self):
        super().__post_init__()
        self.worker_type = "aws_ec2"
        raise NotImplementedError(
            "AwsEc2Worker is not yet implemented. "
            "Planned for future release. "
            "Will use boto3 for AWS EC2 cloud execution.\n"
            "Requires: pip install ras-commander[remote-aws]"
        )


def init_aws_ec2_worker(**kwargs) -> AwsEc2Worker:
    """Initialize AWS EC2 worker (stub - raises NotImplementedError)."""
    check_aws_dependencies()
    kwargs['worker_type'] = 'aws_ec2'
    return AwsEc2Worker(**kwargs)
