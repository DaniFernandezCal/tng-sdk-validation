#!/bin/bash
#
# Install the packager and run its unittests to check the integration between:
# - tng-sdk-project
# - tng-sdk-validate
# - tng-sdk-package
#
# (The packager always uses the other two tools, this is why we use its tests
# to test the integration)

set  -e
echo "== SDK integration tests: Prepare..."
tng-wks

echo "== SDK integration tests: Install tng-sdk-package..."
cd /
git clone https://github.com/sonata-nfv/tng-sdk-package.git
cd /tng-sdk-package
python setup.py develop
tng-sdk-package -h

echo "== SDK integration tests: Run tng-sdk-package tests..."
cd /tng-sdk-package
pytest -v

echo "== SDK integration tests: PASSED."
cd /tng-sdk-project