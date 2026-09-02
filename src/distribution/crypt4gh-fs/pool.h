#ifndef __EGA_DIST_POOL_INCLUDED__
#define __EGA_DIST_POOL_INCLUDED__ 1

#include "db.h"

int ega_dist_db_init(const char *dsn,
		     struct dbconn** connections, unsigned int nconnections,
		     pthread_mutex_t *lock, pthread_cond_t *cond);

int ega_dist_db_terminate(struct dbconn* connections, unsigned int nconnections,
			  pthread_mutex_t *lock, pthread_cond_t *cond);


int ega_dist_db_acquire(struct dbconn* connections, unsigned int nconnections,
			pthread_mutex_t *lock, pthread_cond_t *cond);

int ega_dist_db_release(struct dbconn* connections, unsigned int conn_id,
			pthread_mutex_t *lock, pthread_cond_t *cond);

#endif /* ! __EGA_DIST_POOL_INCLUDED__ */
