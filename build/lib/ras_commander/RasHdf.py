

import h5py
import numpy as np
import pandas as pd
from typing import Union, List, Optional, Dict, Callable
from scipy.spatial import KDTree

class RasHdf:
    """
    A class containing utility functions for working with HDF files in the ras-commander library.
    """

    @staticmethod
    def read_hdf_to_dataframe(hdf_dataset: h5py.Dataset, fill_value: Union[int, float, str] = -9999) -> pd.DataFrame:
        """
        Reads an HDF5 table using h5py and converts it into a pandas DataFrame, handling byte strings and missing values.

        Args:
            hdf_dataset (h5py.Dataset): The HDF5 table to read.
            fill_value (Union[int, float, str], optional): The value to use for filling missing data. Defaults to -9999.

        Returns:
            pd.DataFrame: The resulting DataFrame with byte strings decoded and missing values replaced.

        Example:
            >>> with h5py.File('data.h5', 'r') as f:
            ...     dataset = f['my_dataset']
            ...     df = RasHdf.read_hdf_to_dataframe(dataset)
            >>> print(df.head())
        """
        df = RasHdf.convert_to_dataframe_array(hdf_dataset)
        byte_cols = [col for col in df.columns if isinstance(df[col].iloc[0], (bytes, bytearray))]
        test_byte_cols = [col for col in df.columns if isinstance(df[col].iloc[-1], (bytes, bytearray))]
        assert byte_cols == test_byte_cols, "Inconsistent byte string columns detected"
        
        try:
            df[byte_cols] = df[byte_cols].applymap(lambda x: x.decode('utf-8'))
        except Exception as e:
            print(f'WARNING: {e} while decoding byte strings in {hdf_dataset.name}, resuming')
        
        df = df.replace({fill_value: np.NaN})
        return df

    @staticmethod
    def save_dataframe_to_hdf(dataframe: pd.DataFrame, 
                              hdf_parent_group: h5py.Group, 
                              dataset_name: str, 
                              attributes: Optional[Dict[str, Union[int, float, str]]] = None, 
                              fill_value: Union[int, float, str] = -9999, 
                              **kwargs: Union[int, float, str]) -> h5py.Dataset:
        """
        Saves a pandas DataFrame to an HDF5 dataset within a specified parent group.

        This function addresses limitations of `pd.to_hdf()` by using h5py to create and save datasets.

        Args:
            dataframe (pd.DataFrame): The DataFrame to save.
            hdf_parent_group (h5py.Group): The parent HDF5 group where the dataset will be created.
            dataset_name (str): The name of the new dataset to add in the HDF5 parent group.
            attributes (Optional[Dict[str, Union[int, float, str]]], optional): A dictionary of attributes to add to the dataset. Defaults to None.
            fill_value (Union[int, float, str], optional): The value to use for filling missing data. Defaults to -9999.
            **kwargs: Additional keyword arguments passed to `hdf_parent_group.create_dataset()`.

        Returns:
            h5py.Dataset: The created HDF5 dataset within the parent group.

        Example:
            >>> df = pd.DataFrame({'A': [1, 2, 3], 'B': ['a', 'b', 'c']})
            >>> with h5py.File('data.h5', 'w') as f:
            ...     group = f.create_group('my_group')
            ...     dataset = RasHdf.save_dataframe_to_hdf(df, group, 'my_dataset')
            >>> print(dataset)
        """
        df = dataframe.copy()

        if df.columns.dtype == 'O':
            df.columns = df.columns.str.replace('/', '-')
        
        df = df.fillna(fill_value)
        
        string_cols = [col for col in df.columns if isinstance(df[col].iloc[0], str)]
        test_string_cols = [col for col in df.columns if isinstance(df[col].iloc[-1], str)]
        assert string_cols == test_string_cols, "Inconsistent string columns detected"
        
        df[string_cols] = df[string_cols].applymap(lambda x: x.encode('utf-8')).astype('bytes')

        if isinstance(df.columns, pd.RangeIndex):
            arr = df.values
        else:
            arr_dt = [(col, df[col].dtype) for col in df.columns]
            arr = np.empty((len(df),), dtype=arr_dt)
            for col in df.columns:
                arr[col] = df[col].values
    
        if dataset_name in hdf_parent_group:
            del hdf_parent_group[dataset_name]
        
        dataset = hdf_parent_group.create_dataset(dataset_name, data=arr, **kwargs)
        
        if attributes:
            dataset.attrs.update(attributes)
        
        return dataset

    @staticmethod
    def perform_kdtree_query(reference_points: np.ndarray, query_points: np.ndarray, max_distance: float = 2.0) -> np.ndarray:
        """
        Performs a KDTree query between two datasets and returns indices with distances exceeding max_distance set to -1.

        Args:
            reference_points (np.ndarray): The reference dataset for KDTree.
            query_points (np.ndarray): The query dataset to search against KDTree of reference_points.
            max_distance (float, optional): The maximum distance threshold. Indices with distances greater than this are set to -1. Defaults to 2.0.

        Returns:
            np.ndarray: Array of indices from reference_points that are nearest to each point in query_points. 
                        Indices with distances > max_distance are set to -1.

        Example:
            >>> ref_points = np.array([[0, 0], [1, 1], [2, 2]])
            >>> query_points = np.array([[0.5, 0.5], [3, 3]])
            >>> RasHdf.perform_kdtree_query(ref_points, query_points)
            array([ 0, -1])
        """
        dist, snap = KDTree(reference_points).query(query_points, distance_upper_bound=max_distance)
        snap[dist > max_distance] = -1
        return snap

    @staticmethod
    def find_nearest_neighbors(points: np.ndarray, max_distance: float = 2.0) -> np.ndarray:
        """
        Creates a self KDTree for dataset points and finds nearest neighbors excluding self, 
        with distances above max_distance set to -1.

        Args:
            points (np.ndarray): The dataset to build the KDTree from and query against itself.
            max_distance (float, optional): The maximum distance threshold. Indices with distances 
                                            greater than max_distance are set to -1. Defaults to 2.0.

        Returns:
            np.ndarray: Array of indices representing the nearest neighbor in points for each point in points. 
                        Indices with distances > max_distance or self-matches are set to -1.

        Example:
            >>> points = np.array([[0, 0], [1, 1], [2, 2], [10, 10]])
            >>> RasHdf.find_nearest_neighbors(points)
            array([1, 0, 1, -1])
        """
        dist, snap = KDTree(points).query(points, k=2, distance_upper_bound=max_distance)
        snap[dist > max_distance] = -1
        
        snp = pd.DataFrame(snap, index=np.arange(len(snap)))
        snp = snp.replace(-1, np.nan)
        snp.loc[snp[0] == snp.index, 0] = np.nan
        snp.loc[snp[1] == snp.index, 1] = np.nan
        filled = snp[0].fillna(snp[1])
        snapped = filled.fillna(-1).astype(np.int64).to_numpy()
        return snapped

    @staticmethod
    def consolidate_dataframe(dataframe: pd.DataFrame, 
                              group_by: Optional[Union[str, List[str]]] = None, 
                              pivot_columns: Optional[Union[str, List[str]]] = None, 
                              level: Optional[int] = None, 
                              n_dimensional: bool = False, 
                              aggregation_method: Union[str, Callable] = 'list') -> pd.DataFrame:
        """
        Consolidate rows in a DataFrame by merging duplicate values into lists or using a specified aggregation function.

        Args:
            dataframe (pd.DataFrame): The DataFrame to consolidate.
            group_by (Optional[Union[str, List[str]]], optional): Columns or indices to group by. Defaults to None.
            pivot_columns (Optional[Union[str, List[str]]], optional): Columns to pivot. Defaults to None.
            level (Optional[int], optional): Level of multi-index to group by. Defaults to None.
            n_dimensional (bool, optional): If True, use a pivot table for N-Dimensional consolidation. Defaults to False.
            aggregation_method (Union[str, Callable], optional): Aggregation method, e.g., 'list' to aggregate into lists. Defaults to 'list'.

        Returns:
            pd.DataFrame: The consolidated DataFrame.

        Example:
            >>> df = pd.DataFrame({'A': [1, 1, 2], 'B': [4, 5, 6], 'C': [7, 8, 9]})
            >>> RasHdf.consolidate_dataframe(df, group_by='A')
               B         C
            A            
            1  [4, 5]  [7, 8]
            2  [6]     [9]
        """
        if aggregation_method == 'list':
            agg_func = lambda x: tuple(x)
        else:
            agg_func = aggregation_method

        if n_dimensional:
            result = dataframe.pivot_table(group_by, pivot_columns, aggfunc=agg_func)
        else:
            result = dataframe.groupby(group_by, level=level).agg(agg_func).applymap(list)

        return result

    @staticmethod
    def decode_byte_strings(dataframe: pd.DataFrame) -> pd.DataFrame:
        """
        Decodes byte strings in a DataFrame to regular string objects.

        This function converts columns with byte-encoded strings (e.g., b'string') into UTF-8 decoded strings.

        Args:
            dataframe (pd.DataFrame): The DataFrame containing byte-encoded string columns.

        Returns:
            pd.DataFrame: The DataFrame with byte strings decoded to regular strings.

        Example:
            >>> df = pd.DataFrame({'A': [b'hello', b'world'], 'B': [1, 2]})
            >>> RasHdf.decode_byte_strings(df)
                 A  B
            0  hello  1
            1  world  2
        """
        str_df = dataframe.select_dtypes(['object'])
        str_df = str_df.stack().str.decode('utf-8').unstack()
        for col in str_df:
            dataframe[col] = str_df[col]
        return dataframe

    @staticmethod
    def find_nearest_value(array: Union[list, np.ndarray], target_value: Union[int, float]) -> Union[int, float]:
        """
        Finds the nearest value in a NumPy array to the specified target value.

        Args:
            array (Union[list, np.ndarray]): The array to search within.
            target_value (Union[int, float]): The value to find the nearest neighbor to.

        Returns:
            Union[int, float]: The nearest value in the array to the specified target value.

        Example:
            >>> arr = np.array([1, 3, 5, 7, 9])
            >>> RasHdf.find_nearest_value(arr, 6)
            5
        """
        array = np.asarray(array)
        idx = (np.abs(array - target_value)).argmin()
        return array[idx]

