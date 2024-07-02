# JB Tenant

This is a package which provides support for tenant configuration. The package contains a tenant DB, a tenant repository class and tenant onboarding & maintenance scripts. Currently the Generic QA service uses the tenant package.

<br>

# 🔧 1. Installation

To use the code, you need to follow these steps:

1. Clone the repository from GitHub:

   ```bash
   git clone git@github.com:OpenNyAI/jugalbandi.git
   ```

2. The code requires **Python 3.7 or higher** and the project follows poetry package system. If poetry is already installed, skip this step. To install [poetry](https://python-poetry.org/docs/), run the following command in your terminal:

   ```bash
   curl -sSL https://install.python-poetry.org | python3 -
   ```

3. Once poetry is installed, go into the **jb-tenant** folder under the **packages** folder in the terminal and run the following commands to install the dependencies and create a virtual environment:

   ```bash
   poetry install
   source .venv/bin/activate
   ```

# 👩‍💻 2. Usage

Once the above installation steps are completed, you can export this package to other services to use the tenant DB configuration as needed. Additionally, you can also use the tenant onboarding and maintenance scripts to create and update tenants. To use the scripts, you will need to create a **.env** file in the **jb-tenant** folder or in the **root folder of any other service** which uses this package and add the following environment variables:

```bash
# To connect to DB
POSTGRES_DATABASE_IP=<your_db_public_ip>
POSTGRES_DATABASE_PORT=5432
POSTGRES_DATABASE_USERNAME=<your_db_username>
POSTGRES_DATABASE_PASSWORD=<your_db_password>
POSTGRES_DATABASE_NAME=<your_db_name>
```
