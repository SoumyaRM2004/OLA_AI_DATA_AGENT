import psycopg2

class DatabaseConnection:
  
    def __init__(self,db_config):
      self.db_config = db_config
      try:
        self.connection=psycopg2.connect(**db_config)
        print("Connected to database successfully")
      except Exception as e:
        print(f"Error in connecting to database: {e}")
        self.connection=None
        
    def schema_details(self,schema_name):
      
      schema_info_context= "" 
      connection=self.connection
      cursor=connection.cursor()
      schema_info_context=f"Database Schema : {schema_name}\n "
      
      try: 
        
        cursor.execute("select table_name from information_schema.tables where table_schema = %s; ", (schema_name,))
        table_list=cursor.fetchall()
        
        for table in table_list:
          table_name=table[0]
          schema_info_context=f"{schema_info_context}\n Table:{table_name}\n"
          
          #Adding Colums and Data Types
          
          cursor.execute("select column_name, data_type from information_schema.columns where table_name=%s;", (table_name,))
          column_list=cursor.fetchall()
          
          for column in column_list:
            column_name=column[0]
            data_type=column[1]
            schema_info_context=f"{schema_info_context} Column: {column_name}, Data Type: {data_type}\n"
            
          #Adding sample data
            
          cursor.execute (f"select * from {schema_name}.{table_name} limit 5")
          sample_data=cursor.fetchall()
          
          schema_info_context=f"{schema_info_context}\n Sample Data: {sample_data}\n"
          for row in sample_data:
            schema_info_context=f"{schema_info_context} {row}\n"
          
          
      
      except Exception as e:
        print(f"Error in fetching schema details: {e}")
        schema_info_context=f"Error fetching schema details: {e} "
        
      finally:
        if cursor:
          cursor.close()
          
        if connection:
          connection.close()
          
      return schema_info_context
          
    def execute_query(self, query):
      try:
        connection = self.connection
        cursor = connection.cursor()

        cursor.execute(query)

        result = cursor.fetchall()

        connection.commit()

        return str(result)

      except Exception as e:

        print(f"Error Executing query : {e}")

        return f"SQL execution error: {e}"

      finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()
    
          
if __name__ == "__main__":
  import os
  from dotenv import load_dotenv
  load_dotenv()

  obj = DatabaseConnection(
    {
      "host": os.getenv("host", "localhost"),
      "port": os.getenv("port", "5432"),
      "dbname": os.getenv("database", "postgres"),
      "user": os.getenv("user", "postgres"),
      "password": os.getenv("password"),
    }
  )

  result = obj.schema_details("public")
  with open("test_schema_details.txt", "w") as f:
    f.write(result)
    print("Schema details written to test_schema_details.txt")
          
