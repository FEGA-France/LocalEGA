/* #define DEBUG 1 */
/* #include "debug.h" */

#include "includes.h"

/* DB connection status or thread id */
#define AVAILABLE  -1
#define ERROR      -2

int
ega_dist_db_init(const char *dsn,
		 struct dbconn** connections,
		 unsigned int nconnections,
		 pthread_mutex_t *lock,
		 pthread_cond_t *cond )
__attribute__((nonnull))
{
  D3("Initializing the DB lock");
  if(pthread_mutex_init(lock, NULL )) {
    E("Couldn't initialize the DB lock");
    return 1;
  }
	
  D3("Initializing the DB waiting queue");
  if(pthread_cond_init( cond, NULL )) {
    E("Couldn't initialize the DB condition variable");
    pthread_mutex_destroy( lock );
    return 2;
  }

  /* Not multithreaded yet */
  D2("Preparing %d DB connections", nconnections);
  struct dbconn* conns = (struct dbconn*)malloc( nconnections * sizeof(struct dbconn));
  if(conns == NULL){
    E("Couldn't allocation the DB connections");
    return 1;
  }
  int i;
  for( i = 0; i < nconnections; i++ ) {
    struct dbconn *conn = &conns[i];
    conn->conninfo = dsn;
    conn->conn = NULL;
    conn->busy = AVAILABLE;
  }

  *connections = conns;
  return 0;
}

int
ega_dist_db_terminate(struct dbconn* connections,
		      unsigned int nconnections,
		      pthread_mutex_t *lock,
		      pthread_cond_t *cond )
__attribute__((nonnull))
{
  int i = 0;
  struct dbconn *conn = NULL;

  D1("Terminating the DB pool");
	
  for(; i < nconnections; i++ ) {
    conn = &connections[i];
    if(conn->conn){
      if(conn->busy > 0){
	E("Destroying db connection %d to thread '%d' which is still in use", i, conn->busy);
      } else {
	D3("Closing database connection %d", i);
      }
      PQfinish(conn->conn);
    }
    conn->conn = NULL;
    conn->busy = AVAILABLE;
  }	

  return (pthread_cond_destroy( cond ) ||
	  pthread_mutex_destroy( lock ));
}

/*
 * Returns 0 if and only if ok.
 */
static int
is_connection_ok(int conn_id, struct dbconn* c)
{
  if(c->conn == NULL){
    D3("Initializing DB connection %d", conn_id);
    c->conn = PQconnectdb(c->conninfo);
    D2("Contacting postgres://[redacted]@%s:%s/%s", PQhost(c->conn), PQport(c->conn), PQdb(c->conn));
    if( PQstatus(c->conn) != CONNECTION_OK ){
      E("Bad Connection [%d]: %s", errno, PQerrorMessage(c->conn));
      return 1;
    }

    D3("Testing DB connection %d", conn_id);
    c->rows = PQexec(c->conn, "SELECT 1;");
    if (PQresultStatus(c->rows) != PGRES_TUPLES_OK) {
      E("Database ping error: %s", PQresultErrorMessage(c->rows));
      PQclear(c->rows);
      return 2; /* fail */
    }
    D3("ping successful for DB connection %d", conn_id);
    return 0;

  } else { /* already initialized */

    if( PQstatus( c->conn ) == CONNECTION_OK )
      return 0;
    
  }
  return 3;
}

int
ega_dist_db_acquire(struct dbconn* connections,
		    unsigned int nconnections,
		    pthread_mutex_t *lock,
		    pthread_cond_t *cond)
__attribute__((nonnull))
{
  int res, i;
  struct dbconn *conn = NULL;
  D1("Acquiring a DB connection");

  for(;;){

    D3("Getting a lock on the DB pool");
    res = pthread_mutex_lock( lock );
    if( res < 0 ) {
      E("Locking mutex failed for thread '%u': %d", (unsigned int)pthread_self( ), res );
      return -1;
    }
		
    /* find a free connection, remember pid */
    for(i = 0; i < nconnections; i++ ) {
      conn = &connections[i];
      if( conn->busy == AVAILABLE ) {
	D1("DB connection %d seems available", i);
	if( is_connection_ok(i, conn) == 0 ) { /* if ok, take it */
	  conn->busy = pthread_self( );
	  res = i; /* success */
	  goto bailout;
	}
	conn->busy = ERROR;
      }
    }

    /* Non-available, wait until a free connection is signalled */
    D1("Waiting for DB connection to be available");
    res = pthread_cond_wait( cond, lock );
    if( res < 0 ) {
      E("Error waiting for free condition in thread '%u': %d",
	(unsigned int)pthread_self( ), res );
      res = -3;
      goto bailout;
    }
    
    (void)pthread_mutex_unlock( lock );
  } /* try again */
  
bailout:
  D3("Releasing the lock on the DB pool");
  (void)pthread_mutex_unlock( lock );
  D2("Acquiring DB connection return %d", res);
  return res;
}


int
ega_dist_db_release(struct dbconn* connections,
		    unsigned int conn_id,
		    pthread_mutex_t *lock,
		    pthread_cond_t *cond)
__attribute__((nonnull))
{
  int res;
  int i;
  
  res = pthread_mutex_lock( lock );
  if( res < 0 ) return res;

  struct dbconn *conn = &connections[conn_id];
  conn->busy = AVAILABLE;
	
  (void)pthread_mutex_unlock( lock );
  (void)pthread_cond_signal( cond );
	
  return 0;
}

