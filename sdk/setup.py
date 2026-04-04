from setuptools import setup, find_packages

setup(
    name="tokenops-sdk",
    version="1.0.0",
    description="TokenOps Python SDK — track LLM costs across all providers",
    author="Ercan Holasoglu",
    url="https://github.com/ercanholasoglu/tokenops",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "httpx>=0.26.0",
        "pydantic>=2.0.0",
        "loguru>=0.7.0",
    ],
    extras_require={
        "dev": ["pytest", "sqlalchemy"],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Topic :: Software Development :: Libraries",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
    ],
)
