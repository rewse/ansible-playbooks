<?php if ( $wp_query->max_num_pages > 1 ) : ?>
    <div class="archive-nav clear">
        <?php if ( get_next_posts_link() ) : ?>
            <div class="archive-nav-button fright">
                <?php echo get_next_posts_link( __( 'Older posts', 'fukasawa' ) . ' &rarr;' ); ?>
            </div>
        <?php endif; ?>
        <?php if ( get_previous_posts_link() ) : ?>
            <div class="archive-nav-button fleft">
                <?php echo get_previous_posts_link( '&larr; ' . __( 'Newer posts', 'fukasawa' ) ); ?>
            </div>
        <?php endif; ?>
    </div><!-- .archive-nav -->
<?php endif; ?>
