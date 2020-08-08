from functools import lru_cache
from functools import wraps


@lru_cache(maxsize=2)
def nprocs():
    """Gets number of processes or returns 1 if mpi is not installed

    Returns
    -------
    int:
        Rank of process or 1 if MPI is not installed

    """
    try:
        from mpi4py import MPI
    except ImportError:
        return 1

    comm = MPI.COMM_WORLD

    return comm.Get_size()



@lru_cache(maxsize=2)
def get_rank():
    """Gets rank or returns 0 if mpi is not installed

    Returns
    -------
    int:
        Rank of process or 0 if MPI is not installed

    """

    try:
        from mpi4py import MPI
    except ImportError:
        return 0

    comm = MPI.COMM_WORLD
    rank = comm.Get_rank()

    return rank

def scatter(data, root=0):
    from mpi4py import MPI
    comm = MPI.COMM_WORLD
    if len(data) < nprocs():
        raise ValueError('not enough processes! work in progress')
    else:
        data = comm.scatter(data, root=root)
    return data

def gather(data, root=0):
    from mpi4py import MPI
    comm = MPI.COMM_WORLD
    data = comm.gather(data, root=root)
    return data

# def only_master_rank(f):
#     """
#     A decorator to ensure only the master
#     MPI rank can run it
#     """
#     @wraps(f)
#     def wrapper(*args, **kwargs):
#         if get_rank() == 0:
#             return f(*args, **kwargs)
#     return wrapper


