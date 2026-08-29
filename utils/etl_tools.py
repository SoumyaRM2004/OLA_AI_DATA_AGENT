import os
import requests
import pandas as pd

class ETLTools:
  
  def __init__(Self):
    pass
  
  def extract_load(self,url:str,output_folder:str,format:str):
    """
        This tool extracts the data from the API (url) and loads it inti the  the
        desired location(output_folder)
        
        Args:
            url: The URL of the API from which the data is to be extracted.
            output_folder: The folder path where the extracted data is to be loaded.
            
        Returns:
            str: A message indicating the suceesss or failure of the operation
    """
    
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    
    output_folder=os.path.join(project_root,output_folder)
    
    try:
      response = requests.get(url)
      response.raise_for_status()
      data=response.json()
      
      filename=os.path.join(output_folder,f"extracted_data.{format}")
      os.makedirs(output_folder,exist_ok=True)
      
      df=pd.json_normalize(data['results'])
      if format=="csv":
        df.to_csv(filename,index=False)
      elif format=="json":
        df.to_json(filename,orient='records',lines=True)
      elif format=="parquet":
        df.to_parquet(filename,index=False)
      else:
        return f"Error: Unsupported format '{format}'"
      return f"Successfully extracted data saved to {filename}"
    
    except Exception as e:
      return f"Error in extracting data: {e}"

  def transform_load_context(self,file_path:str):
    """
        This tool transforms the data from the given file_path and loads it into the
        desired location(output_folder)
        
        Args:
            file_path: The path to the file from which the data is to be extracted.
            output_folder: The folder path where the transformed data is to be loaded.
            
        Returns:
            str: A message indicating the success or failure of the operation
    """
    file_extension=os.path.splitext(file_path)[1].lower()
    if file_extension==".csv":
      df=pd.read_csv(file_path)
    elif file_extension==".json":
      df=pd.read_json(file_path)
    elif file_extension==".parquet":
      df=pd.read_parquet(file_path)
    else:
      return f"Error: Unsupported file format '{file_extension}'"

    top_3_rows=str(df.head(3))
    
    return top_3_rows
  
  def execute_code(self,code:str):
    """
        This tool executes the given code and returns the output
        
        Args:
            code: The code to be executed
            
        Returns:
            str: A message indicating the success or failure of the operation
    """
    try:
      exec(code)   #execute the code
      return f"Successfully executed code"
    except Exception as e:
      return f"Error in executing code: {e}"
    

if __name__=="__main__":
  obj=ETLTools()
  path="D:\\Project\\OLA_AI_DataAgent\\data\\extract\\extracted_data.csv"
  print(obj.transform_load_context(path))
      

