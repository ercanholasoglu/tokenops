from setuptools import setup, find_packages

setup(
    name="tokenops-sdk",
    version="0.1.0",
    description="TokenOps Python SDK — track LLM costs in 3 lines",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="TokenOps",
    url="https://github.com/yourname/tokenops",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "httpx>=0.26.0",
        "pydantic>=2.0.0",
    ],
    extras_require={
        "dev": ["pytest", "pytest-asyncio", "respx"],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Topic :: Software Development :: Libraries",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
    ],
)
